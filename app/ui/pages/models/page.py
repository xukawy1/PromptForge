from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout,
    QComboBox,
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
        self._loading_table = False

        layout = QVBoxLayout(self)
        title = QLabel("模型中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("本地 Ollama 或云端 API（GPT / DeepSeek / GLM / Kimi / 通义等）：动态发现模型，"
                                "选中即自动记住为默认模型，下次打开无需重设。"))

        conn_group = QGroupBox("Ollama 本地连接")
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

        api_group = QGroupBox("API 接入（OpenAI 兼容协议）")
        api_form = QFormLayout(api_group)
        self.vendor_combo = QComboBox()
        try:
            from app.services.providers.openai_compat import VENDOR_PRESETS
            for key, (label, url) in VENDOR_PRESETS.items():
                self.vendor_combo.addItem(label, key)
        except Exception:
            self.vendor_combo.addItem("自定义", "custom")
        self.vendor_combo.currentIndexChanged.connect(self._vendor_changed)
        api_form.addRow("厂商", self.vendor_combo)
        self.api_base = QLineEdit(self.model_service.config.get("api_base_url", "") if self.model_service else "")
        self.api_base.setPlaceholderText("https://api.deepseek.com/v1")
        api_form.addRow("Base URL", self.api_base)
        self.api_key = QLineEdit(self.model_service.config.get("api_key", "") if self.model_service else "")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-…（仅保存在本机 config.json）")
        api_form.addRow("API Key", self.api_key)
        api_row = QHBoxLayout()
        api_save_btn = QPushButton("保存并测试连接")
        api_save_btn.setObjectName("primary")
        api_save_btn.clicked.connect(self.refresh_api_models)
        api_row.addWidget(api_save_btn)
        api_row.addStretch()
        api_form.addRow("操作", api_row)
        self.api_status = QLabel("未配置（API 为可选项，不影响本地 Ollama 使用）")
        self.api_status.setWordWrap(True)
        api_form.addRow("状态", self.api_status)
        layout.addWidget(api_group)
        self._restore_vendor()

        model_group = QGroupBox("已发现模型（点击任意一行即自动记住为默认 LLM）")
        model_layout = QVBoxLayout(model_group)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["模型名称", "来源/类型", "参数量", "大小"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
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
        self._load_db_models()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)

    # ---------- 连接与刷新 ----------

    def _vendor_changed(self):
        if not self.model_service:
            return
        key = self.vendor_combo.currentData()
        from app.services.providers.openai_compat import VENDOR_PRESETS
        _label, url = VENDOR_PRESETS.get(key, ("", ""))
        if url:
            self.api_base.setText(url)

    def _restore_vendor(self):
        if not self.model_service:
            return
        key = self.model_service.config.get("api_vendor", "custom")
        idx = self.vendor_combo.findData(key)
        if idx >= 0:
            self.vendor_combo.setCurrentIndex(idx)

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
        self._run_async("Ollama 刷新", self._refresh_worker)

    def _refresh_worker(self, ctx):
        ctx.report_progress(30)
        result = self.model_service.test_connection()
        ctx.report_progress(70)
        result["sync"] = self.model_service.refresh_remote_models()
        ctx.report_progress(95)
        return result

    def refresh_api_models(self):
        if not self.model_service:
            return
        vendor = self.vendor_combo.currentData() or "custom"
        self.model_service.config.set("api_vendor", vendor)
        self.model_service.set_api_config(self.api_base.text(), self.api_key.text())
        self.api_status.setText("正在连接 API……")
        self._run_async("API 刷新", self._api_refresh_worker)

    def _api_refresh_worker(self, ctx):
        ctx.report_progress(30)
        result = self.model_service.test_api_connection()
        ctx.report_progress(70)
        result["sync"] = self.model_service.refresh_api_models()
        ctx.report_progress(95)
        return result

    # ---------- 默认模型 ----------

    def _selected_model_name(self):
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).text()

    def _on_row_selected(self):
        """点击任意一行即自动记住为默认 LLM（用户需求：选择一次，之后打开仍然生效）。"""
        if self._loading_table:
            return
        name = self._selected_model_name()
        if not name or not self.model_service:
            return
        try:
            self.model_service.set_default("llm", name)
        except Exception as exc:
            self.status.setText(f"记住默认模型失败：{exc}")
            return
        self.status.setText(f"已自动记住：{name} 为本机默认 LLM（下次打开仍然生效）。")
        self.update_defaults_label()

    def set_llm(self):
        self._set_default("llm")
    def set_vision(self):
        self._set_default("vision")
    def set_embedding(self):
        self._set_default("embedding")

    def _set_default(self, model_type):
        name = self._selected_model_name()
        if not name or not self.model_service:
            self.status.setText("请先在表格中选择一个模型。")
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
                self._handle_result(fn(_NullCtx()), label)
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
        label = self._active_tasks.pop(task_id)
        self.progress.setText("后台任务：无")
        self._handle_result(result, label)

    def _on_task_failed(self, task_id, message):
        if task_id not in self._active_tasks:
            return
        label = self._active_tasks.pop(task_id)
        self.progress.setText("后台任务：无")
        if label == "API 刷新":
            self.api_status.setText(f"API 连接失败：{message}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "API 连接失败", str(message))
        else:
            self._show_error(message)
            self._load_db_models()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "无法连接 Ollama",
                f"{message}\n\n提示：\n• 请确认 Ollama 已启动（开始菜单搜索 Ollama 并打开，或运行 ollama serve）；\n"
                "• 也可以直接使用下方「API 接入」调用云端模型（DeepSeek / GLM / OpenAI 等）。\n"
                "下方列表已展示上次发现过的模型，可先选择使用。")

    def _load_db_models(self):
        """从本地模型表加载已同步过的模型（Ollama 未启动时仍可选择）。"""
        if not self.model_service:
            return
        rows = self.model_service.list_models()
        models = [{
            "name": r.get("name") or "",
            "size": 0,
            "provider_label": "API" if str(r.get("provider") or "").startswith("api:") else "本地 Ollama",
            "parameter_size": "",
        } for r in rows]
        if models and self.table.rowCount() == 0:
            self._fill_table(models)
            self.status.setText(f"已从本地记录加载 {len(models)} 个模型（点击任意一行即自动记住为默认 LLM）。")

    def _handle_result(self, result, label="Ollama 刷新"):
        models = result.get("models") or []
        sync = result.get("sync") or {}
        if label == "API 刷新":
            self.api_status.setText(
                f"API 连接成功：{result.get('base_url')}（{result.get('model_count', 0)} 个模型；新增 {sync.get('added', 0)}，更新 {sync.get('updated', 0)}）")
        else:
            self.conn_status.setText(f"连接成功：{result.get('endpoint')}（发现 {result.get('model_count', 0)} 个模型）")
            self.status.setText(f"模型清单已同步：新增 {sync.get('added', 0)}，更新 {sync.get('updated', 0)}。")
        self._fill_table(models)
        self.update_defaults_label()

    def _fill_table(self, models):
        self._rows = models
        self._loading_table = True
        self.table.setRowCount(0)
        for item in models:
            row = self.table.rowCount()
            self.table.insertRow(row)
            size_mb = (item.get("size") or 0) / (1024 * 1024)
            model_type = self.model_service.classify_model(item.get("name") or "") if self.model_service else ""
            values = [
                item.get("name") or "",
                item.get("provider_label") or model_type,
                item.get("parameter_size") or "",
                f"{size_mb:.0f} MB" if size_mb >= 1 else "-",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self._loading_table = False

    def _show_error(self, message):
        self.conn_status.setText("连接失败")
        self.status.setText(f"失败：{message}")
