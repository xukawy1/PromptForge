from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QComboBox, QCheckBox, QLineEdit, QFormLayout, QListWidget, QGroupBox,
    QProgressBar,
)
from PySide6.QtCore import Signal


class GeneratorPage(QWidget):
    stream_text = Signal(str)
    stream_done = Signal()

    def __init__(self, generation_service=None, pattern_service=None, task_manager=None, knowledge_service=None):
        super().__init__()
        self.generation_service = generation_service
        self.pattern_service = pattern_service
        self.task_manager = task_manager
        self.knowledge_service = knowledge_service
        self._active_tasks = {}
        self._variable_edits = {}
        self._stream_buffer = ""
        self.current_result = ""

        layout = QVBoxLayout(self)
        title = QLabel("Prompt 生成")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("输入需求，结合模板与知识库上下文，调用本地模型生成中英双语提示词并入库。"))

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("需求描述"))
        self.input = QTextEdit()
        self.input.setPlaceholderText("例如：赛博朋克城市夜景中的少女半身像，霓虹灯光，电影感……（中文描述即可，输出为英文提示词+中文翻译）")
        self.input.setMinimumHeight(130)
        left.addWidget(self.input)

        template_group = QGroupBox("模板（可选）")
        template_form = QFormLayout(template_group)
        self.template_combo = QComboBox()
        self.template_combo.addItem("不使用模板", None)
        self.template_combo.currentIndexChanged.connect(self.on_template_changed)
        template_form.addRow("选择模板", self.template_combo)
        self.variables_form = QFormLayout()
        template_form.addRow("变量", self.variables_form)
        left.addWidget(template_group)

        self.use_context = QCheckBox("检索知识库/文档/Prompt 作为上下文（关键词 RAG）")
        left.addWidget(self.use_context)
        self.generate_btn = QPushButton("开始生成")
        self.generate_btn.clicked.connect(self.generate)
        left.addWidget(self.generate_btn)

        progress_label = QLabel("生成进度")
        progress_label.setObjectName("sectionTitle")
        left.addWidget(progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        left.addWidget(self.progress_bar)
        self.progress_info = QLabel("等待任务")
        self.progress_info.setObjectName("panelHint")
        left.addWidget(self.progress_info)
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        left.addWidget(self.status)
        left.addStretch()
        body.addLayout(left, 2)

        right = QVBoxLayout()
        result_label = QLabel("扩写提示词")
        result_label.setObjectName("sectionTitle")
        right.addWidget(result_label)
        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        right.addWidget(self.result_box, 1)
        parsed_row = QHBoxLayout()
        self.parsed = QLabel("解析：尚未生成")
        self.parsed.setObjectName("panelHint")
        self.parsed.setWordWrap(True)
        parsed_row.addWidget(self.parsed, 1)
        self.save_btn = QPushButton("保存到 Prompt 库")
        self.save_btn.clicked.connect(self.save_prompt)
        self.save_kb_btn = QPushButton("保存到知识库…")
        self.save_kb_btn.clicked.connect(self.save_to_knowledge)
        parsed_row.addWidget(self.save_btn)
        parsed_row.addWidget(self.save_kb_btn)
        right.addLayout(parsed_row)
        right.addWidget(QLabel("最近生成记录"))
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        right.addWidget(self.history_list)
        body.addLayout(right, 3)
        layout.addLayout(body)

        self.stream_text.connect(self._on_stream_text)
        self.refresh_templates()
        self.refresh_history()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)

    # ---------- 模板与变量 ----------

    def refresh_templates(self):
        self.template_combo.blockSignals(True)
        while self.template_combo.count() > 1:
            self.template_combo.removeItem(self.template_combo.count() - 1)
        self._templates = []
        if self.pattern_service:
            self._templates = self.pattern_service.templates.list_all()
            for row in self._templates:
                self.template_combo.addItem(row.get("name") or "(未命名模板)", row["id"])
        self.template_combo.blockSignals(False)
        self.on_template_changed()

    def on_template_changed(self):
        while self.variables_form.rowCount():
            self.variables_form.removeRow(0)
        self._variable_edits = {}
        template_id = self.template_combo.currentData()
        if not template_id or not self.pattern_service:
            return
        for var in self.pattern_service.variables(template_id):
            edit = QLineEdit(str(var.get("default_value") or ""))
            self._variable_edits[var["variable_name"]] = edit
            self.variables_form.addRow(var.get("display_name") or var["variable_name"], edit)

    # ---------- 生成 ----------

    def generate(self):
        if not self.generation_service:
            self.status.setText("生成服务尚未初始化")
            return
        requirement = self.input.toPlainText().strip()
        if not requirement:
            self.status.setText("请先输入需求描述。")
            return
        template_id = self.template_combo.currentData()
        variables = {name: edit.text() for name, edit in self._variable_edits.items()}
        use_context = self.use_context.isChecked()
        self.generate_btn.setEnabled(False)
        self.status.setText("正在生成……")
        self._stream_buffer = ""
        self.result_box.setPlainText("")
        self.progress_bar.setRange(0, 0)
        self.progress_info.setText("模型生成中（进度按已生成内容增长）……")
        if not self.task_manager:
            try:
                outcome = self.generation_service.generate(
                    requirement, template_id, variables, use_context,
                    on_chunk=self._make_chunk_reporter(),
                )
                self._handle_result(outcome)
            except Exception as exc:
                self._show_error(str(exc))
            finally:
                self._reset_progress()
                self.generate_btn.setEnabled(True)
            return
        if self._active_tasks:
            self.status.setText("已有生成任务在执行，请稍候。")
            self.generate_btn.setEnabled(True)
            return

        def worker(ctx):
            outcome = self.generation_service.generate(
                requirement, template_id, variables, use_context,
                on_chunk=self._make_chunk_reporter(ctx),
            )
            ctx.report_progress(100)
            return outcome

        task_id, future, ctx = self.task_manager.submit(
            fn=worker, task_type="generation.生成",
            input_data={"requirement": requirement},
        )
        self._active_tasks[task_id] = "生成"

    def _make_chunk_reporter(self, ctx=None):
        def report(text, delta):
            if ctx is not None:
                ctx.report_progress(min(99.0, 2.0 + len(text) / 30.0))
            self.stream_text.emit(text)
        return report

    def _on_stream_text(self, text):
        self._stream_buffer = text
        self.result_box.setPlainText(text)
        self.progress_info.setText(f"已生成 {len(text)} 字符……")

    def _on_task_progress(self, task_id, value):
        if task_id in self._active_tasks:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(value))

    def _on_task_finished(self, task_id, outcome):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id, None)
        self._reset_progress()
        self.generate_btn.setEnabled(True)
        self._handle_result(outcome)

    def _on_task_failed(self, task_id, message):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id, None)
        self._reset_progress()
        self.generate_btn.setEnabled(True)
        self._show_error(message)

    def _reset_progress(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if self.current_result else 0)
        if not self.current_result:
            self.progress_info.setText("等待任务")

    def _handle_result(self, outcome):
        self.current_result = outcome.get("result") or ""
        parsed = self.generation_service.parse_result(self.current_result)
        self.result_box.setPlainText(self.current_result)
        negative = parsed.get("negative") or ""
        self.parsed.setText(
            f"英文 {len(parsed.get('en') or '')} 字 · 中文 {len(parsed.get('zh') or '')} 字 · 负向 {len(negative)} 字 · 参数 {'有' if parsed.get('params') else '无'}"
        )
        context = outcome.get("context") or []
        note = f"已检索 {len(context)} 条上下文。" if context else "未使用上下文。"
        self.progress_info.setText(f"生成完成，共 {len(self.current_result)} 字符")
        self.status.setText(f"生成完成，{note}结果已写入生成历史，可在下方保存到 Prompt 库。")
        self.refresh_history()

    def _show_error(self, message):
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.status.setText(f"需要先配置模型：{message}")
            self.progress_info.setText("等待配置模型")
            offer_model_center(self, message)
            return
        self.status.setText(f"生成失败：{message}")
        self.progress_info.setText("任务失败")

    # ---------- 入库与历史 ----------

    def save_prompt(self):
        if not self.current_result or not self.generation_service:
            self.status.setText("还没有可保存的生成结果。")
            return
        try:
            outcome = self.generation_service.save_as_prompt(self.current_result)
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return
        self.status.setText(outcome.get("message", "已保存"))

    def save_to_knowledge(self):
        if not self.current_result or not self.generation_service:
            self.status.setText("还没有可保存的生成结果。")
            return
        if not self.knowledge_service:
            self.status.setText("知识库服务尚未初始化。")
            return
        from app.ui.pages.collector.dialogs import SaveKnowledgeDialog
        from app.services.generation_service import GenerationService
        parsed = GenerationService.parse_result(self.current_result)
        default_title = (parsed.get("en") or "")[:24] or "AI 生成提示词"
        dialog = SaveKnowledgeDialog(self.knowledge_service, default_title=default_title, parent=self)
        if not dialog.exec():
            self.status.setText("已取消保存（保存到知识库必须选择知识分类并填写名称）。")
            return
        data = dialog.data()
        content = self.current_result
        if data.get("category_id") is None:
            self.status.setText("未选择知识分类，已取消保存。")
            return
        try:
            knowledge_id = self.knowledge_service.create_knowledge({
                "source_type": "generation", "source_id": None,
                "title": (data["title"] or default_title)[:120],
                "content": content,
                "summary": "同步自 Prompt 生成",
                "category_id": data["category_id"],
                "knowledge_type": "prompt",
                "confidence": 1.0,
            })
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return
        self.status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")

    def refresh_history(self):
        self.history_list.clear()
        if not self.generation_service:
            return
        for row in self.generation_service.list_history(15):
            created = (row.get("created_at") or "")[:19]
            preview = (row.get("user_input") or "")[:40]
            self.history_list.addItem(f"{created}  {preview}")
