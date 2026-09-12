from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout,
)


class _NullCtx:
    def report_progress(self, value):
        pass


class ModelsPage(QWidget):
    def __init__(self, model_service=None, task_manager=None):
        super().__init__()
        self.model_service = model_service
        self.task_manager = task_manager
        self._active_tasks = {}
        self._rows = []

        layout = QVBoxLayout(self)
        title = QLabel("模型中心")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel("连接本地 Ollama 服务，动态发现已安装模型；所有模型名称均来自服务发现，不预置清单。"))

        conn_group = QGroupBox("Ollama 连接")
        conn_form = QFormLayout(conn_group)
        endpoint_row = QHBoxLayout()
        self.endpoint = QLineEdit(self.model_service.config.get("ollama_endpoint", "http://127.0.0.1:11434") if self.model_service else "")
        self.endpoint.setPlaceholderText("http://127.0.0.1:11434")
        save_btn = QPushButton("保存地址")
        save_btn.clicked.connect(self.save_endpoint)
        test_btn = QPushButton("测试连接并刷新模型")
        test_btn.clicked.connect(self.refresh_models)
        endpoint_row.addWidget(self.endpoint, 1)
        endpoint_row.addWidget(save_btn)
        endpoint_row.addWidget(test_btn)
        conn_form.addRow("服务地址", endpoint_row)
        self.conn_status = QLabel("未测试")
        conn_form.addRow("状态", self.conn_status)
        layout.addWidget(conn_group)

        model_group = QGroupBox("已发现模型")
        model_layout = QVBoxLayout(model_group)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["模型名称", "类型", "参数量", "大小"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        model_layout.addWidget(self.table)
        default_row = QHBoxLayout()
        for label, slot in (("设为默认 LLM", self.set_llm), ("设为默认 Vision", self.set_vision), ("设为默认 Embedding", self.set_embedding)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            default_row.addWidget(btn)
        default_row.addStretch()
        model_layout.addLayout(default_row)
        layout.addWidget(model_group, 1)

        self.defaults_label = QLabel("当前默认模型：未知")
        layout.addWidget(self.defaults_label)
        self.progress = QLabel("后台任务：无")
        layout.addWidget(self.progress)
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.update_defaults_label()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)

    # ---------- 连接与刷新 ----------

    def save_endpoint(self):
        if not self.model_service:
            return
        self.model_service.set_endpoint(self.endpoint.text())
        self.conn_status.setText("地址已保存，可点击“测试连接并刷新模型”。")

    def refresh_models(self):
        if not self.model_service:
            self.status.setText("模型服务尚未初始化")
            return
        self.model_service.set_endpoint(self.endpoint.text())
        self.conn_status.setText("正在连接……")
        self._run_async("测试连接", self._refresh_worker)

    def _refresh_worker(self, ctx):
        ctx.report_progress(30)
        result = self.model_service.test_connection()
        ctx.report_progress(70)
        result["sync"] = self.model_service.refresh_remote_models()
        ctx.report_progress(95)
        return result

    # ---------- 默认模型 ----------

    def _selected_model_name(self):
        items = self.table.selectedItems()
        if not items:
            self.status.setText("请先在表格中选择一个模型。")
            return None
        return self.table.item(items[0].row(), 0).text()

    def set_llm(self):
        self._set_default("llm")
    def set_vision(self):
        self._set_default("vision")
    def set_embedding(self):
        self._set_default("embedding")

    def _set_default(self, model_type):
        name = self._selected_model_name()
        if not name or not self.model_service:
            return
        try:
            self.model_service.set_default(model_type, name)
        except Exception as exc:
            self.status.setText(f"设置失败：{exc}")
            return
        self.status.setText(f"已将 {name} 设为默认 {model_type.upper()}。")
        self.update_defaults_label()

    def update_defaults_label(self):
        if not self.model_service:
            self.defaults_label.setText("当前默认模型：未知")
            return
        defaults = self.model_service.defaults()
        self.defaults_label.setText(
            f"当前默认模型：LLM={defaults.get('llm') or '未设置'} · Vision={defaults.get('vision') or '未设置'} · Embedding={defaults.get('embedding') or '未设置'}"
        )

    # ---------- 后台任务 ----------

    def _run_async(self, label, fn):
        if not self.task_manager:
            try:
                self._handle_result(fn(_NullCtx()))
            except Exception as exc:
                self._show_error(str(exc))
            return
        if self._active_tasks:
            self.status.setText("已有模型中心任务在执行，请稍候。")
            return
        task_id, future, ctx = self.task_manager.submit(fn=fn, task_type=f"modelcenter.{label}", input_data={"label": label})
        self._active_tasks[task_id] = label
        self.progress.setText(f"后台任务：{label}（0%）")

    def _on_task_progress(self, task_id, value):
        if task_id in self._active_tasks:
            self.progress.setText(f"后台任务：{self._active_tasks[task_id]}（{value:.0f}%）")

    def _on_task_finished(self, task_id, result):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id, None)
        self.progress.setText("后台任务：无")
        self._handle_result(result)

    def _on_task_failed(self, task_id, message):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id, None)
        self.progress.setText("后台任务：无")
        self._show_error(message)

    def _handle_result(self, result):
        models = result.get("models") or []
        self.conn_status.setText(f"连接成功：{result.get('endpoint')}（发现 {result.get('model_count', 0)} 个模型）")
        sync = result.get("sync") or {}
        self.status.setText(f"模型清单已同步：新增 {sync.get('added', 0)}，更新 {sync.get('updated', 0)}。")
        self._fill_table(models)
        self.update_defaults_label()

    def _fill_table(self, models):
        self._rows = models
        self.table.setRowCount(0)
        for item in models:
            row = self.table.rowCount()
            self.table.insertRow(row)
            size_mb = (item.get("size") or 0) / (1024 * 1024)
            values = [
                item.get("name") or "",
                self.model_service.classify_model(item.get("name") or "") if self.model_service else "",
                item.get("parameter_size") or "",
                f"{size_mb:.0f} MB" if size_mb >= 1 else "-",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def _show_error(self, message):
        self.conn_status.setText("连接失败")
        self.status.setText(f"失败：{message}")
