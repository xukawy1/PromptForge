from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTextEdit, QFileDialog, QMessageBox, QGroupBox, QFormLayout, QFrame,
    QListWidget, QSplitter, QStackedWidget, QCheckBox, QProgressBar,
)


class CollectorPage(QWidget):
    collection_completed = Signal(object)

    PAGE_TEXT, PAGE_FILE, PAGE_URL = 0, 1, 2

    def __init__(self, service=None, task_manager=None, model_service=None, knowledge_service=None, config=None):
        super().__init__()
        self.service = service
        self.task_manager = task_manager
        self.model_service = model_service
        self.knowledge_service = knowledge_service
        self.config = config or {}
        self._active_tasks = {}
        self._organize_tasks = {}
        self._history_rows = []
        self._build_ui()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)
            self.task_manager.task_cancelled.connect(self._on_task_cancelled)

    # ---------------- UI ----------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("采集中心")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        action_row = QHBoxLayout()
        self.auto_organize = QCheckBox("采集完成后自动规整到知识库")
        self.auto_organize.setChecked(bool(self.config.get("auto_organize", False)) if hasattr(self.config, "get") else False)
        self.auto_organize.toggled.connect(self._auto_organize_changed)
        self.view_result_btn = QPushButton("查看采集结果（规整 / 预览 / 保存）")
        self.view_result_btn.setObjectName("primary")
        self.view_result_btn.setEnabled(False)
        self.view_result_btn.clicked.connect(self.open_result_dialog)
        action_row.addWidget(self.auto_organize)
        action_row.addStretch(1)
        action_row.addWidget(self.view_result_btn)
        layout.addLayout(action_row)
        hint = QLabel("左侧选择采集方式 → 采集完成后点「查看采集结果」：自动拆分出综合总结与分散提示词，"
                      "可按类别归档保存、大模型扩写、一键保存全部（重复导入自动覆盖旧记录）。")
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        splitter = QSplitter()

        # ---- 左侧：功能分类 + 采集历史 ----
        left = QWidget(); left_layout = QVBoxLayout(left)
        caption = QLabel("采集方式")
        caption.setObjectName("sectionTitle")
        left_layout.addWidget(caption)
        self.function_list = QListWidget()
        for item in ("📝 手工文本采集", "📁 本地文件采集", "🌐 网页 URL 采集"):
            self.function_list.addItem(item)
        self.function_list.currentRowChanged.connect(self._switch_page)
        left_layout.addWidget(self.function_list, 2)
        history_caption = QLabel("采集历史")
        history_caption.setObjectName("sectionTitle")
        left_layout.addWidget(history_caption)
        self.history_list = QListWidget()
        self.history_list.currentRowChanged.connect(self._show_history_item)
        left_layout.addWidget(self.history_list, 3)
        refresh_row = QHBoxLayout()
        self.refresh_history_btn = QPushButton("刷新历史")
        self.refresh_history_btn.clicked.connect(self.load_history)
        refresh_row.addStretch(); refresh_row.addWidget(self.refresh_history_btn)
        left_layout.addLayout(refresh_row)
        splitter.addWidget(left)

        # ---- 右侧：分页采集表单 ----
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_text_page())
        self.stack.addWidget(self._build_file_page())
        self.stack.addWidget(self._build_url_page())
        splitter.addWidget(self.stack)
        splitter.setSizes([280, 720])
        layout.addWidget(splitter, 1)

        # ---- 结果区 ----
        # 归纳结果区域由各采集页的大文本框承担（见 _build_url_page / _build_file_page）

        self.progress = QLabel("后台任务：无")
        self.cancel_btn = QPushButton("取消当前任务")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_current_task)
        task_row = QHBoxLayout(); task_row.addWidget(self.progress); task_row.addStretch(); task_row.addWidget(self.cancel_btn)
        layout.addLayout(task_row)
        self.status = QLabel("就绪")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.function_list.setCurrentRow(0)
        QTimer.singleShot(0, self.load_history)

    def _build_text_page(self):
        page = QWidget(); form_root = QVBoxLayout(page)
        text_group = QGroupBox("手工文本采集")
        form = QFormLayout(text_group)
        self.text_title = QLineEdit()
        self.text_title.setPlaceholderText("可选；留空将自动从正文标题或首行识别")
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("粘贴文章、Prompt、笔记或知识内容……")
        form.addRow("标题", self.text_title)
        form.addRow("内容", self.text_edit)
        self.text_count = QLabel("0 字")
        self.text_edit.textChanged.connect(self._update_text_count)
        btn = QPushButton("采集并保存到知识库…")
        btn.clicked.connect(self._save_text_to_knowledge)
        row = QHBoxLayout(); row.addWidget(self.text_count); row.addStretch(); row.addWidget(btn)
        form.addRow("统计", row)
        form_root.addWidget(text_group); form_root.addStretch()
        return page

    def _build_file_page(self):
        page = QWidget(); form_root = QVBoxLayout(page)
        file_group = QGroupBox("本地文件采集")
        file_layout = QVBoxLayout(file_group)
        file_layout.addWidget(QLabel(
            "支持的格式：TXT / MD / CSV / JSON / LOG / DOCX / PDF / PNG / JPG / WEBP / BMP / GIF / TIFF\n"
            "图片会自动导入图片库，供“图片反推”页面解析内嵌 Metadata 或 AI 视觉反推。"
        ))
        file_row = QHBoxLayout()
        file_row.addStretch()
        file_btn = QPushButton("选择文件并采集…")
        file_btn.clicked.connect(self._choose_file)
        file_row.addWidget(file_btn)
        file_layout.addLayout(file_row)
        form_root.addWidget(file_group)

        ocr_group = QGroupBox("识别与归纳（文件正文 + 图片内文字 → 普通格式提示词）")
        ocr_form = QFormLayout(ocr_group)
        ocr_row = QHBoxLayout()
        self.file_ocr_btn = QPushButton("识别图片文字并归纳")
        self.file_ocr_btn.clicked.connect(lambda: self.summarize_web(widget="file"))
        self.file_ocr_again_btn = QPushButton("重新识别归纳")
        self.file_ocr_again_btn.clicked.connect(lambda: self.summarize_web(widget="file"))
        file_save_btn = QPushButton("保存到知识库…")
        file_save_btn.clicked.connect(self.save_web_summary)
        ocr_row.addWidget(self.file_ocr_btn)
        ocr_row.addWidget(self.file_ocr_again_btn)
        ocr_row.addWidget(file_save_btn)
        ocr_row.addStretch()
        ocr_form.addRow("操作", ocr_row)
        self.file_summary = QTextEdit()
        self.file_summary.setPlaceholderText(
            "采集文件后点击“识别图片文字并归纳”：文件正文与图片中识别出的文字会归纳成普通格式的提示词描述。\n"
            "归纳结果随窗体自动缩放显示，可直接编辑；不满意点“重新识别归纳”，满意后选择知识分类保存到知识库。")
        self.file_summary.setMinimumHeight(300)
        ocr_form.addRow("归纳结果（可编辑）", self.file_summary)
        self.file_ocr_status = QLabel("")
        self.file_ocr_status.setObjectName("panelHint")
        self.file_ocr_status.setWordWrap(True)
        ocr_form.addRow("状态", self.file_ocr_status)
        form_root.addWidget(ocr_group, 1)
        return page

    def _build_url_page(self):
        page = QWidget(); form_root = QVBoxLayout(page)
        url_group = QGroupBox("网页 URL 采集")
        url_form = QFormLayout(url_group)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/article 或微信公众号文章链接")
        self.url_title = QLineEdit()
        self.url_title.setPlaceholderText("可选；留空自动读取网页标题")
        url_form.addRow("URL", self.url_edit)
        url_form.addRow("标题", self.url_title)
        url_btn = QPushButton("开始采集网页")
        url_btn.clicked.connect(self._collect_url)
        url_form.addRow("操作", url_btn)
        form_root.addWidget(url_group)

        ocr_group = QGroupBox("识别与归纳（网页正文 + 图片内文字 → 普通格式提示词）")
        ocr_form = QFormLayout(ocr_group)
        ocr_row = QHBoxLayout()
        self.ocr_btn = QPushButton("识别图片文字并归纳")
        self.ocr_btn.clicked.connect(lambda: self.summarize_web())
        self.ocr_again_btn = QPushButton("重新识别归纳")
        self.ocr_again_btn.clicked.connect(lambda: self.summarize_web())
        save_kb_btn = QPushButton("保存到知识库…")
        save_kb_btn.clicked.connect(self.save_web_summary)
        ocr_row.addWidget(self.ocr_btn)
        ocr_row.addWidget(self.ocr_again_btn)
        ocr_row.addWidget(save_kb_btn)
        ocr_row.addStretch()
        ocr_form.addRow("操作", ocr_row)
        self.url_summary = QTextEdit()
        self.url_summary.setPlaceholderText(
            "采集网页后点击“识别图片文字并归纳”：网页正文与图片中识别出的文字会归纳成普通格式的提示词描述。\n"
            "结果可直接编辑；不满意点“重新识别归纳”，满意后选择知识分类保存到知识库。")
        self.url_summary.setMinimumHeight(300)
        ocr_form.addRow("归纳结果（可编辑）", self.url_summary)
        self.ocr_status = QLabel("")
        self.ocr_status.setObjectName("panelHint")
        self.ocr_status.setWordWrap(True)
        ocr_form.addRow("状态", self.ocr_status)
        form_root.addWidget(ocr_group, 1)
        return page

    # ---------------- 网页识别归纳 ----------------

    def summarize_web(self, widget="web"):
        self._summary_widget = widget
        status = self.ocr_status if widget == "web" else self.file_ocr_status
        if not self.service:
            status.setText("采集服务尚未初始化")
            return
        source_id = self._latest_source_id()
        if source_id is None:
            status.setText("请先完成一次采集（或在左侧历史中选中条目）。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if widget == "web":
            self.ocr_btn.setEnabled(False); self.ocr_again_btn.setEnabled(False)
        else:
            self.file_ocr_btn.setEnabled(False); self.file_ocr_again_btn.setEnabled(False)
        status.setText("识别中：正在读取正文与图片文字并归纳……图片较多时需要等待。")
        if not self.task_manager:
            try:
                outcome = organizer.summarize_web_source(source_id, self.model_service)
                self._handle_web_summary(outcome)
            except Exception as exc:
                status.setText(f"识别失败：{exc}")
            finally:
                if widget == "web":
                    self.ocr_btn.setEnabled(True); self.ocr_again_btn.setEnabled(True)
                else:
                    self.file_ocr_btn.setEnabled(True); self.file_ocr_again_btn.setEnabled(True)
            return
        if self._organize_tasks:
            status.setText("已有识别任务在执行。")
            if widget == "web":
                self.ocr_btn.setEnabled(True); self.ocr_again_btn.setEnabled(True)
            else:
                self.file_ocr_btn.setEnabled(True); self.file_ocr_again_btn.setEnabled(True)
            return

        model_service = self.model_service
        def worker(ctx):
            ctx.report_progress(20)
            outcome = organizer.summarize_web_source(source_id, model_service)
            ctx.report_progress(95)
            return outcome

        task_id, future, ctx = self.task_manager.submit(
            fn=worker, task_type="collector.ocrsum", input_data={"label": "网页识别归纳"})
        self._organize_tasks[task_id] = {"source_id": source_id, "kind": "web_summary", "widget": widget}
        status.setText("识别中……")

    def _handle_web_summary(self, outcome):
        widget = getattr(self, "_summary_widget", "web")
        target = self.url_summary if widget == "web" else self.file_summary
        status = self.ocr_status if widget == "web" else self.file_ocr_status
        target.setPlainText(outcome.get("summary") or "")
        parts = outcome.get("ocr_parts") or []
        note = f"已识别 {len(parts)} 张图片文字" if parts else "未识别到图片文字（可在模型中心设置 Vision 模型后重试）"
        models = " · ".join(m for m in (outcome.get("ocr_model"), outcome.get("llm_model")) if m)
        status.setText(f"归纳完成（{note}；模型：{models or '关键词规整'}）。可编辑后保存到知识库。")

    def save_web_summary(self):
        widget = getattr(self, "_summary_widget", "web")
        status = self.ocr_status if widget == "web" else self.file_ocr_status
        summary_box = self.url_summary if widget == "web" else self.file_summary
        if not self.knowledge_service:
            status.setText("知识库服务尚未初始化")
            return
        summary = summary_box.toPlainText().strip()
        if not summary:
            status.setText("还没有归纳结果可保存，请先点击“识别图片文字并归纳”。")
            return
        source_id = self._latest_source_id()
        if source_id is None:
            status.setText("没有对应的采集来源。")
            return
        from app.ui.pages.collector.dialogs import SaveKnowledgeDialog
        dialog = SaveKnowledgeDialog(self.knowledge_service, default_title=(self.url_title.text().strip() or "归纳提示词"), parent=self)
        if not dialog.exec():
            status.setText("已取消保存（保存到知识库需要选择分类与名称）。")
            return
        data = dialog.data()
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        try:
            knowledge_id = organizer.save_summary_to_knowledge(source_id, summary, title=data["title"], category_id=data["category_id"])
        except Exception as exc:
            status.setText(f"保存失败：{exc}")
            return
        status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")
        self.load_history()

    # ---------------- 页面切换 ----------------

    def _switch_page(self, row):
        index = {0: self.PAGE_TEXT, 1: self.PAGE_FILE, 2: self.PAGE_URL}.get(row, 0)
        self.stack.setCurrentIndex(index)

    # ---------------- 采集动作 ----------------

    def _update_text_count(self):
        if self.service:
            meta = self.service.build_text_metadata(self.text_edit.toPlainText(), self.text_title.text())
            self.text_count.setText(f"{meta['char_count']} 字符 · {meta['word_count']} 计数单位 · {meta['language']} · {meta['content_type']}")
        else:
            self.text_count.setText(f"{len(self.text_edit.toPlainText().strip())} 字符")

    def _save_text(self):
        if not self.service:
            self._show_error("采集服务尚未初始化"); return
        try:
            self._run_async("文本采集", self.service.collect_text, self.text_edit.toPlainText(), self.text_title.text())
        except Exception as exc:
            self._show_error(str(exc))

    def _save_text_to_knowledge(self):
        if not self.service:
            self._show_error("采集服务尚未初始化"); return
        text = self.text_edit.toPlainText().strip()
        if not text:
            self._show_error("请先粘贴要采集的文本内容"); return
        try:
            result = self.service.collect_text(self.text_edit.toPlainText(), self.text_title.text())
        except Exception as exc:
            self._show_error(str(exc)); return
        self._handle_result(result)
        if result.get("status") == "duplicate":
            return
        default_title = self.text_title.text().strip() or (result.get("metadata") or {}).get("title", "")
        self._save_source_to_knowledge(result.get("source_id"), default_title=default_title)

    def _save_source_to_knowledge(self, source_id, default_title=""):
        if source_id is None or not self.knowledge_service:
            self.status.setText("知识库服务尚未初始化，无法保存到知识库。")
            return
        from app.ui.pages.collector.dialogs import SaveKnowledgeDialog
        dialog = SaveKnowledgeDialog(self.knowledge_service, default_title=default_title, parent=self)
        if not dialog.exec():
            self.status.setText("已取消保存（保存到知识库需要选择分类与名称）。")
            return
        data = dialog.data()
        try:
            data_content = self.service.load_source_content(source_id) or {}
            content = data_content.get("content") or ""
        except Exception:
            content = ""
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        try:
            knowledge_id = organizer.save_summary_to_knowledge(source_id, content, title=data["title"], category_id=data["category_id"])
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return
        self.status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")
        self.load_history()

    def open_result_dialog(self):
        source_id = self._latest_source_id()
        if source_id is None:
            QMessageBox.information(self, "暂无采集结果", "请先完成一次采集，再查看结果。")
            return
        items = self.history_list.selectedIndexes()
        row = None
        if items and 0 <= items[0].row() < len(self._history_rows):
            row = self._history_rows[items[0].row()]
        else:
            row = self._history_rows[0] if self._history_rows else None
        if not row:
            return
        from app.ui.pages.collector.dialogs import CollectorResultDialog
        dialog = CollectorResultDialog(self.service, self.knowledge_service, self.model_service,
                                       self.task_manager, row, parent=self)
        dialog.exec()
        self.load_history()

    def _choose_file(self):
        if not self.service:
            self._show_error("采集服务尚未初始化"); return
        path, _ = QFileDialog.getOpenFileName(self, "选择资料文件", "", "支持的文件 (*.txt *.md *.csv *.json *.log *.docx *.pdf *.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff)")
        if not path: return
        self._run_async("文件采集", self.service.collect_file, path)

    def _collect_url(self):
        if not self.service:
            self._show_error("采集服务尚未初始化"); return
        self._run_async("网页采集", self.service.collect_url, self.url_edit.text(), self.url_title.text())

    def _run_async(self, label, fn, *args):
        if not self.task_manager:
            try: self._handle_result(fn(*args))
            except Exception as exc: self._show_error(str(exc))
            return
        if self._active_tasks:
            QMessageBox.information(self, "任务进行中", "当前已有采集任务，请等待完成或先取消。")
            return
        def worker(ctx):
            ctx.report_progress(5)
            result = fn(*args)
            ctx.report_progress(95)
            return result
        task_id, future, ctx = self.task_manager.submit(
                fn=worker,
                task_type=f"collection.{label}",
                input_data={
                    "label": label,
                    "args": list(args),
                    "execution_plan": {
                        "kind": "collector",
                        "operation": label,
                        "version": 1,
                    },
                },
            )
        self._active_tasks[task_id] = label
        self.progress.setText(f"后台任务：{label}（0%）")
        self.cancel_btn.setEnabled(True)
        self.status.setText(f"已提交后台任务：{label}")

    # ---------------- 任务回调 ----------------

    def _on_task_progress(self, task_id, value):
        if task_id in self._active_tasks:
            self.progress.setText(f"后台任务：{self._active_tasks[task_id]}（{value:.0f}%）")
        elif task_id in self._organize_tasks:
            self.status.setText(f"规整中……{value:.0f}%")

    def _finish_task(self, task_id):
        self._active_tasks.pop(task_id, None)
        self.cancel_btn.setEnabled(False)
        self.progress.setText("后台任务：无")

    def _on_task_finished(self, task_id, result):
        if task_id in self._active_tasks:
            self._finish_task(task_id)
            self._handle_result(result)
        elif task_id in self._organize_tasks:
            info = self._organize_tasks.pop(task_id)
            if info.get("kind") == "web_summary":
                if info.get("widget") == "web":
                    self.ocr_btn.setEnabled(True); self.ocr_again_btn.setEnabled(True)
                else:
                    self.file_ocr_btn.setEnabled(True); self.file_ocr_again_btn.setEnabled(True)
                self._handle_web_summary(result)
            else:
                self._handle_organize(result, info)

    def _on_task_failed(self, task_id, message):
        if task_id in self._active_tasks:
            self._finish_task(task_id)
            self._show_error(message)
        elif task_id in self._organize_tasks:
            info = self._organize_tasks.pop(task_id)
            if info.get("kind") == "web_summary":
                if info.get("widget") == "web":
                    self.ocr_btn.setEnabled(True); self.ocr_again_btn.setEnabled(True)
                    self.ocr_status.setText(f"识别失败：{message}")
                else:
                    self.file_ocr_btn.setEnabled(True); self.file_ocr_again_btn.setEnabled(True)
                    self.file_ocr_status.setText(f"识别失败：{message}")
            else:
                self.status.setText(f"规整失败：{message}")

    def _on_task_cancelled(self, task_id):
        if task_id in self._active_tasks:
            self._finish_task(task_id)
            self.status.setText("采集任务已取消")

    def _cancel_current_task(self):
        for task_id in list(self._active_tasks):
            self.task_manager.cancel(task_id)

    # ---------------- 结果与预览 ----------------

    def _handle_result(self, result):
        status = result.get("status")
        self.status.setText(result.get("message", "处理完成"))
        meta = result.get("metadata") or {}
        detail = [f"状态：{status or 'unknown'}"]
        if result.get("source_id") is not None: detail.append(f"来源ID：{result['source_id']}")
        if result.get("document_id") is not None: detail.append(f"文档ID：{result['document_id']}")
        if result.get("image_id") is not None: detail.append(f"图片ID：{result['image_id']}")
        if result.get("file_name"): detail.append(f"文件：{result['file_name']}")
        if meta:
            if meta.get("title"): detail.append(f"标题：{meta['title']}")
            if meta.get("language"): detail.append(f"语言：{meta['language']}")
            if meta.get("content_type"): detail.append(f"类型：{meta['content_type']}")
            if meta.get("word_count") is not None: detail.append(f"字数/计数：{meta['word_count']}")
            if meta.get("char_count") is not None: detail.append(f"字符：{meta['char_count']}")
        self._last_detail = " · ".join(detail)
        self._last_result = result
        self._preview_current(result)
        self.load_history()
        self.view_result_btn.setEnabled(result.get("source_id") is not None)
        if status == "duplicate": QMessageBox.information(self, "重复资料", result.get("message", "内容已存在"))
        elif status == "created":
            QMessageBox.information(self, "采集完成", result.get("message", "采集成功"))
            if self.auto_organize.isChecked():
                self.organize_current(use_llm=False)
        elif status == "failed": QMessageBox.warning(self, "采集失败", result.get("message", "采集失败"))
        # 记录当前来源，保证「查看采集结果」始终对应当前导入的网址
        self._current_source_id = result.get("source_id")
        if status == "duplicate" and result.get("source_id") is not None:
            self.status.setText(result.get("message", "重复导入") + "——已同步到该网址已有记录，可直接点「查看采集结果」。")
        self.collection_completed.emit(result)

    def _show_error(self, message):
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.status.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        self.status.setText(f"采集失败：{message}")
        QMessageBox.warning(self, "采集失败", message)

    # ---------------- 采集历史 ----------------

    def showEvent(self, event):
        super().showEvent(event)
        self.load_history()

    def load_history(self):
        if not self.service:
            return
        self._history_rows = self.service.recent_sources(50)
        self.history_list.clear()
        for row in self._history_rows:
            created = (row.get("created_at") or "")[:19]
            kind = row.get("source_type") or "manual"
            self.history_list.addItem(f"{created}  [{kind}]  {row.get('title') or '(未命名)'}")

    def _show_history_item(self, index):
        """选中历史条目：网页来源自动回填到右侧 URL/标题栏，便于同步查看与重采。"""
        if not (self.service and 0 <= index < len(self._history_rows)):
            return
        source = self._history_rows[index]
        self._current_source_id = source.get("id")
        url = (source.get("url") or "").strip()
        title = source.get("title") or "(未命名)"
        if url:
            self.function_list.setCurrentRow(2)  # 切到网页采集页
            self.url_edit.setText(url)
            self.url_title.setText(title)
            self.status.setText(f"已同步历史网页到右侧：标题「{title}」 URL「{url}」。可直接查看采集结果或重新采集。")
        else:
            self.status.setText(f"已选中历史：{title}（类型：{source.get('source_type') or ''}）。"
                                "点右上角「查看采集结果」可拆分提示词、规整并保存到知识库。")

    def _preview_current(self, result):
        # 预览已由各采集页的归纳结果框承担；保留空实现避免旧调用报错。
        return

    def _preview_current(self, result):
        # 预览已由各采集页的归纳结果框承担；保留空实现避免旧调用报错。
        return

    # ---------------- 规整到知识库 ----------------

    def _auto_organize_changed(self, checked):
        if hasattr(self.config, "set"):
            self.config.set("auto_organize", bool(checked))

    def organize_current(self, use_llm):
        if not self.knowledge_service:
            self.status.setText("知识库服务尚未初始化")
            return
        source_id = self._latest_source_id()
        if source_id is None:
            self.status.setText("请先完成一次采集，或在左侧历史中选择条目。")
            return
        self._organize(source_id, use_llm)

    def _latest_source_id(self):
        """来源解析优先级：URL 输入框匹配的已采集来源 → 最近一次采集 → 历史选中 → 最新历史。"""
        if self.service:
            url_text = self.url_edit.text().strip()
            if url_text:
                row = self.service.find_source_by_url(url_text)
                if row:
                    return row["id"]
        if getattr(self, "_current_source_id", None) is not None:
            return self._current_source_id
        items = self.history_list.selectedIndexes()
        if items and 0 <= items[0].row() < len(self._history_rows):
            return self._history_rows[items[0].row()]["id"]
        if self._history_rows:
            return self._history_rows[0]["id"]
        return None

    def _organize(self, source_id, use_llm):
        if not self.service:
            self.status.setText("采集服务尚未初始化")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.organize_source(source_id, use_llm=use_llm, model_service=self.model_service)
                self._handle_organize(outcome, {"source_id": source_id})
            except Exception as exc:
                self.status.setText(f"规整失败：{exc}")
            return
        if self._organize_tasks:
            self.status.setText("已有规整任务在执行。")
            return

        def worker(ctx):
            ctx.report_progress(25)
            outcome = organizer.organize_source(source_id, use_llm=use_llm, model_service=self.model_service)
            ctx.report_progress(95)
            return outcome

        task_id, future, ctx = self.task_manager.submit(
            fn=worker, task_type="collector.organize",
            input_data={"label": "规整到知识库"},
        )
        self._organize_tasks[task_id] = {"source_id": source_id}
        self.status.setText("规整中……")

    def _handle_organize(self, outcome, info):
        keywords = outcome.get("keywords") or []
        categories = outcome.get("categories") or []
        self.status.setText(
            f"{outcome.get('message', '')}  分类：{' / '.join(categories) if categories else '未匹配'}  关键词：{', '.join(keywords[:8])}"
        )
        self.load_history()
