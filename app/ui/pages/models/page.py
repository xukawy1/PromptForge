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
        self._auto_refreshed = False

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

        profile_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        apply_profile_btn = QPushButton("应用选中配置")
        apply_profile_btn.clicked.connect(self.apply_api_profile)
        delete_profile_btn = QPushButton("删除选中配置")
        delete_profile_btn.setToolTip("从本机彻底删除该 API 配置与密钥，防止被他人套用")
        delete_profile_btn.clicked.connect(self.delete_api_profile)
        profile_row.addWidget(QLabel("已保存配置"))
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(apply_profile_btn)
        profile_row.addWidget(delete_profile_btn)
        api_form.addRow("配置管理", profile_row)

        save_profile_row = QHBoxLayout()
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("配置名称，如：DeepSeek-主力 / GLM-备用 / 本地代理")
        save_current_btn = QPushButton("保存当前为配置")
        save_current_btn.clicked.connect(self.save_current_profile)
        save_profile_row.addWidget(self.profile_name, 1)
        save_profile_row.addWidget(save_current_btn)
        api_form.addRow("保存配置", save_profile_row)
        self.api_status = QLabel("未配置（API 为可选项，不影响本地 Ollama 使用）")
        self.api_status.setWordWrap(True)
        api_form.addRow("状态", self.api_status)
        layout.addWidget(api_group)
        self._restore_vendor()
        self.refresh_api_profiles()

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
        QTimer.singleShot(400, self._auto_refresh_once)
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

    # ---------- API 配置保存 / 切换 / 删除 ----------

    def refresh_api_profiles(self):
        if not self.model_service:
            return
        profiles = self.model_service.list_api_profiles()
        active = self.model_service.config.get("api_active_profile") or ""
        self.profile_combo.clear()
        params = [("— 选择已保存的配置 —", "")]
        for profile in profiles:
            key = profile.get("api_key") or ""
            masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("已存密钥" if key else "无密钥")
            label = f"{profile.get('name')}（{profile.get('vendor') or 'custom'} · {masked}）"
            if profile.get("name") == active:
                label = "★ " + label
            params.append((label, profile.get("name")))
        if active:
            idx = self.profile_combo.findData(active)
        else:
            idx = 0
        for label, name in params:
            self.profile_combo.addItem(label, name)
        all_params = [("— 选择已保存的配置 —", "")] + params[1:]
        self.profile_combo.clear()
        for label, name in all_params:
            self.profile_combo.addItem(label, name)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(active)) if active else 0)

    def save_current_profile(self):
        if not self.model_service:
            return
        name = self.profile_name.text().strip()
        if not name:
            vendor_label = self.vendor_combo.currentText()
            name = vendor_label + " 配置"
            self.profile_name.setText(name)
        try:
            self.model_service.save_api_profile(
                name, self.vendor_combo.currentData() or "custom",
                self.api_base.text(), self.api_key.text())
        except Exception as exc:
            self.api_status.setText(f"保存配置失败：{exc}")
            return
        self.refresh_api_profiles()
        self.api_status.setText(f"已保存配置「{name}」并设为当前启用（下次打开自动沿用）。")

    def apply_api_profile(self):
        if not self.model_service:
            return
        name = self.profile_combo.currentData()
        if not name:
            self.api_status.setText("请先在下拉框中选择一个已保存的配置。")
            return
        try:
            profile = self.model_service.apply_api_profile(name)
        except Exception as exc:
            self.api_status.setText(f"应用配置失败：{exc}")
            return
        idx = self.vendor_combo.findData(profile.get("vendor") or "custom")
        if idx >= 0:
            self.vendor_combo.setCurrentIndex(idx)
        self.api_base.setText(profile.get("base_url") or "")
        self.api_key.setText(profile.get("api_key") or "")
        self.refresh_api_profiles()
        self.api_status.setText(f"已切换到配置「{name}」，正在刷新模型清单……")
        self.refresh_api_models()

    def delete_api_profile(self):
        if not self.model_service:
            return
        name = self.profile_combo.currentData()
        if not name:
            self.api_status.setText("请先选择要删除的配置。")
            return
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "删除 API 配置",
            f"将从本机彻底删除配置「{name}」及其 API 密钥。\n"
            "删除后该密钥不再保存在本软件中，其他人无法再通过本机套用。\n\n确定删除吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            outcome = self.model_service.delete_api_profile(name)
        except Exception as exc:
            self.api_status.setText(f"删除失败：{exc}")
            return
        if outcome.get("cleared_active"):
            self.api_base.setText("")
            self.api_key.setText("")
        self.refresh_api_profiles()
        self.api_status.setText(
            f"已删除配置「{name}」" + ("，并清除了当前 API 密钥。" if outcome.get("cleared_active") else "。")
            + f"剩余配置：{outcome.get('remaining', 0)} 套。")

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
        elif label == "自动同步":
            self.conn_status.setText("后台自动同步失败：Ollama 未启动（可手动点“测试连接并刷新模型”，或使用 API 接入）")
            self._load_db_models()
        else:
            self._show_error(message)
            self._load_db_models()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "无法连接 Ollama",
                f"{message}\n\n提示：\n• 请确认 Ollama 已启动（开始菜单搜索 Ollama 并打开，或运行 ollama serve）；\n"
                "• 也可以直接使用下方「API 接入」调用云端模型（DeepSeek / GLM / OpenAI 等）。\n"
                "下方列表已展示上次发现过的模型，可先选择使用。")

    def _auto_refresh_once(self):
        """打开页面后静默尝试一次 Ollama 刷新（失败不弹窗），让模型清单保持最新。"""
        if self._auto_refreshed or self._active_tasks or not self.model_service:
            return
        self._auto_refreshed = True
        self.conn_status.setText("正在后台自动同步模型清单……")
        task_id, future, ctx = self.task_manager.submit(
            fn=self._refresh_worker, task_type="modelcenter.auto", input_data={"label": "自动同步"}
        ) if self.task_manager else (None, None, None)
        if task_id:
            self._active_tasks[task_id] = "自动同步"

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
        # 默认模型行自动高亮（让用户一眼看到上次记住的模型）
        if self.model_service:
            default_llm = self.model_service.config.get("default_llm") or ""
            if default_llm:
                for row in range(self.table.rowCount()):
                    if self.table.item(row, 0) and self.table.item(row, 0).text() == default_llm:
                        self.table.selectRow(row)
                        break
        self._loading_table = False

    def _show_error(self, message):
        self.conn_status.setText("连接失败")
        self.status.setText(f"失败：{message}")
