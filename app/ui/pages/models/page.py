from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout,
    QComboBox, QDialog, QDialogButtonBox, QMessageBox,
)


class _NullCtx:
    def report_progress(self, value):
        pass


class ProviderDialog(QDialog):
    """添加供应商：名称 + 厂商 + Base URL + API Key，保存为一条供应商记录。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加供应商")
        self.resize(560, 300)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("如：DeepSeek-主力 / GLM-备用 / 公司代理")
        self.vendor = QComboBox()
        try:
            from app.services.providers.openai_compat import VENDOR_PRESETS
            for key, (label, url) in VENDOR_PRESETS.items():
                self.vendor.addItem(label, key)
        except Exception:
            self.vendor.addItem("自定义", "custom")
        self.vendor.currentIndexChanged.connect(self._vendor_changed)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-…（仅保存在本机）")
        form.addRow("供应商名称（必填）", self.name)
        form.addRow("厂商类型", self.vendor)
        form.addRow("Base URL", self.base_url)
        form.addRow("API Key", self.api_key)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._vendor_changed()

    def _vendor_changed(self):
        from app.services.providers.openai_compat import VENDOR_PRESETS
        key = self.vendor.currentData()
        _label, url = VENDOR_PRESETS.get(key, ("", ""))
        if url:
            self.base_url.setText(url)

    def _validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "缺少名称", "请填写供应商名称。")
            return
        if not self.base_url.text().strip():
            QMessageBox.warning(self, "缺少地址", "请填写 Base URL。")
            return
        self.accept()

    def data(self):
        return {
            "name": self.name.text().strip(),
            "vendor": self.vendor.currentData() or "custom",
            "base_url": self.base_url.text().strip(),
            "api_key": self.api_key.text().strip(),
        }


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
        layout.addWidget(QLabel("本地 Ollama 或云端 API 供应商：添加供应商即保存一条记录，可随时切换与删除"
                                "（删除会同时清除其后台模型记录与密钥）；选中模型即自动记住为默认，下次打开无需重设。"))

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

        provider_group = QGroupBox("API 供应商（添加一个保存一条，可任意选择启用或删除）")
        provider_layout = QVBoxLayout(provider_group)
        self.provider_table = QTableWidget(0, 5)
        self.provider_table.setHorizontalHeaderLabels(["状态", "供应商名称", "厂商", "Base URL", "密钥"])
        self.provider_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.provider_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.provider_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.provider_table.verticalHeader().setVisible(False)
        self.provider_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.provider_table.setMaximumHeight(170)
        provider_layout.addWidget(self.provider_table)
        row = QHBoxLayout()
        add_btn = QPushButton("添加供应商…")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.add_provider)
        apply_btn = QPushButton("设为当前供应商")
        apply_btn.clicked.connect(self.apply_selected_provider)
        delete_btn = QPushButton("删除供应商（含后台记录）")
        delete_btn.setToolTip("删除该供应商配置与密钥，并清除它同步过的全部模型记录，防止被他人套用")
        delete_btn.clicked.connect(self.delete_selected_provider)
        test_provider_btn = QPushButton("测试所选并刷新模型")
        test_provider_btn.clicked.connect(self.test_selected_provider)
        for b in (add_btn, apply_btn, test_provider_btn, delete_btn):
            row.addWidget(b)
        row.addStretch()
        provider_layout.addLayout(row)
        self.api_status = QLabel("暂无供应商：点「添加供应商…」录入第一套 API（DeepSeek / GLM / OpenAI 等）。")
        self.api_status.setWordWrap(True)
        provider_layout.addWidget(self.api_status)
        layout.addWidget(provider_group)
        self.refresh_providers()

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

    # ---------- 供应商管理 ----------

    def refresh_providers(self):
        if not self.model_service:
            return
        profiles = self.model_service.list_api_profiles()
        active = self.model_service.config.get("api_active_profile") or ""
        self.provider_table.setRowCount(0)
        for profile in profiles:
            row = self.provider_table.rowCount()
            self.provider_table.insertRow(row)
            key = profile.get("api_key") or ""
            masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("已保存" if key else "无")
            values = ["★ 当前" if profile.get("name") == active else "", profile.get("name") or "",
                      profile.get("vendor") or "custom", profile.get("base_url") or "", masked]
            for col, value in enumerate(values):
                self.provider_table.setItem(row, col, QTableWidgetItem(str(value)))
            self.provider_table.item(row, 0).setData(32, profile.get("name") or "")
        self.provider_table.resizeColumnsToContents()
        if profiles:
            self.api_status.setText(
                f"已保存 {len(profiles)} 个供应商" + (f"，当前启用：{active}" if active else "（尚未选择启用，请点「设为当前供应商」）"))

    def _selected_provider_name(self):
        items = self.provider_table.selectedItems()
        if not items:
            return None
        return self.provider_table.item(items[0].row(), 0).data(32)

    def add_provider(self):
        if not self.model_service:
            return
        dialog = ProviderDialog(self)
        if not dialog.exec():
            return
        data = dialog.data()
        try:
            self.model_service.save_api_profile(data["name"], data["vendor"], data["base_url"], data["api_key"])
        except Exception as exc:
            self.api_status.setText(f"添加失败：{exc}")
            return
        self.refresh_providers()
        self.api_status.setText(f"已添加供应商「{data['name']}」并设为当前；正在刷新模型清单……")
        self.refresh_api_models()

    def apply_selected_provider(self):
        if not self.model_service:
            return
        name = self._selected_provider_name()
        if not name:
            self.api_status.setText("请先在列表中选择一个供应商。")
            return
        try:
            profile = self.model_service.apply_api_profile(name)
        except Exception as exc:
            self.api_status.setText(f"切换失败：{exc}")
            return
        self.refresh_providers()
        self.api_status.setText(f"已切换到供应商「{name}」（{profile.get('base_url')}），正在刷新模型清单……")
        self.refresh_api_models()

    def test_selected_provider(self):
        name = self._selected_provider_name()
        if not name:
            self.api_status.setText("请先选择供应商。")
            return
        self.apply_selected_provider()

    def delete_selected_provider(self):
        if not self.model_service:
            return
        name = self._selected_provider_name()
        if not name:
            self.api_status.setText("请先选择要删除的供应商。")
            return
        answer = QMessageBox.question(
            self, "删除供应商",
            f"将删除供应商「{name}」：\n"
            "• 从本机移除其 Base URL 与 API 密钥\n"
            "• 清除它同步过的全部模型记录（后台记录）\n"
            "• 若它是当前启用供应商，同时清空当前 API 凭据\n\n"
            "删除后其他人无法再通过本机套用该 API。确定删除吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            outcome = self.model_service.delete_api_profile(name)
        except Exception as exc:
            self.api_status.setText(f"删除失败：{exc}")
            return
        self.refresh_providers()
        self._load_db_models()
        msg = f"已删除供应商「{name}」"
        if outcome.get("purged_models"):
            msg += f"，清除后台模型记录 {outcome['purged_models']} 条"
        if outcome.get("cleared_active"):
            msg += "，当前 API 凭据已清空"
        if outcome.get("cleared_defaults"):
            msg += f"，并重置失效的默认模型：{'、'.join(outcome['cleared_defaults'].values())}"
        self.api_status.setText(msg + "。")
        self.update_defaults_label()

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
        self.api_status.setText("正在连接 API 并刷新模型清单……")
        self._run_async("API 刷新", self._api_refresh_worker)

    def _api_refresh_worker(self, ctx):
        ctx.report_progress(30)
        result = self.model_service.test_api_connection()
        ctx.report_progress(70)
        result["sync"] = self.model_service.refresh_api_models()
        ctx.report_progress(95)
        return result

    def _auto_refresh_once(self):
        """打开页面后静默尝试一次 Ollama 刷新（失败不弹窗），让模型清单保持最新。"""
        if self._auto_refreshed or self._active_tasks or not self.model_service:
            return
        self._auto_refreshed = True
        self.conn_status.setText("正在后台自动同步模型清单……")
        if not self.task_manager:
            return
        task_id = self.task_manager.submit(
            fn=self._refresh_worker, task_type="modelcenter.auto", input_data={"label": "自动同步"})[0]
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
            QMessageBox.warning(self, "API 连接失败", str(message))
        elif label == "自动同步":
            self.conn_status.setText("后台自动同步失败：Ollama 未启动（可手动点“测试连接并刷新模型”，或使用 API 供应商）")
            self._load_db_models()
        else:
            self._show_error(message)
            self._load_db_models()
            QMessageBox.warning(
                self, "无法连接 Ollama",
                f"{message}\n\n提示：\n• 请确认 Ollama 已启动（开始菜单搜索 Ollama 并打开，或运行 ollama serve）；\n"
                "• 也可以使用上方「API 供应商」调用云端模型（DeepSeek / GLM / OpenAI 等）。\n"
                "下方列表已展示上次发现过的模型，可先选择使用。")

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
        if label == "API 刷新":
            self._offer_switch_default_to_api(models)

    def _offer_switch_default_to_api(self, models):
        """启用 API 供应商后，如果默认 LLM 还是本地模型，提示并支持一键切换。

        常见困惑"我配了 API 怎么还是慢"：扩写/生成/翻译都跟随默认 LLM，
        而默认 LLM 可能仍然是本地模型，API 配了也不会被用到。
        """
        if not self.model_service or not models:
            return
        current = self.model_service.get_default("llm") or ""
        provider_tag = ""
        if current:
            rows = self.model_service.repo.list(1, 0, "name=?", (current,))
            provider_tag = str(rows[0].get("provider") or "") if rows else ""
        if provider_tag.startswith("api:"):
            return  # 默认 LLM 已经是 API 模型，无需提示
        candidates = [m.get("name") for m in models
                      if m.get("name") and self.model_service.classify_model(m.get("name")) == "llm"]
        if not candidates:
            self.api_status.setText(
                f"{self.api_status.text()}｜注意：当前默认 LLM 仍是本地模型「{current}」，扩写/生成仍会跑本地（较慢）。")
            return
        target = candidates[0]
        vision_candidates = [m.get("name") for m in models
                             if m.get("name") and self.model_service.classify_model(m.get("name")) == "vision"]
        vision_target = vision_candidates[0] if vision_candidates else ""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle("是否把默认模型切换到 API")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"当前默认 LLM 是本地模型「{current or '未设置'}」，扩写/生成/翻译仍会跑在本地（较慢）。")
        extra = f"\n同时把默认 Vision（图片识别）也切换为「{vision_target}」。" if vision_target else ""
        box.setInformativeText(
            f"是否把默认 LLM 切换为该 API 供应商的「{target}」？切换后这些功能都会走 API。{extra}")
        switch = box.addButton(f"切换为 {target}", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("保持本地模型", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is switch:
            try:
                self.model_service.set_default("llm", target)
                if vision_target:
                    self.model_service.set_default("vision", vision_target)
            except Exception as exc:
                self.api_status.setText(f"切换默认模型失败：{exc}")
                return
            self.update_defaults_label()
            self._fill_table(self._rows)
            tail = f"，图片识别改用「{vision_target}」" if vision_target else ""
            self.api_status.setText(f"已把默认 LLM 切换为 API 模型「{target}」{tail}，扩写/生成/翻译/分析将走 API。")

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
