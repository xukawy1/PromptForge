from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QDialogButtonBox, QTextEdit, QPushButton, QMessageBox, QFrame,
    QWidget, QScrollArea, QCheckBox, QSplitter, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer


def _offer_model_switch(parent, hint, status_label=None):
    """模型反复写不出可用内容时，提示换模型 / 改用 API，并可一键跳到模型中心。"""
    if not hint:
        return False
    from PySide6.QtWidgets import QMessageBox
    if status_label is not None:
        status_label.setText("模型多次未能写出可用内容——建议更换模型或改用 API。")
    box = QMessageBox(parent)
    box.setWindowTitle("建议更换模型")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(str(hint))
    goto = box.addButton("去模型中心设置", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("知道了", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is goto:
        from app.ui.model_center_nav import nav
        nav.request_open.emit()
        return True
    return False


class SaveKnowledgeDialog(QDialog):
    """保存到知识库：名称与知识分类必填，未选分类不允许保存。"""

    def __init__(self, knowledge_service, default_title="", parent=None, require_all=True):
        super().__init__(parent)
        self.setWindowTitle("保存到知识库")
        self.require_all = require_all
        form = QFormLayout(self)
        self.name = QLineEdit(default_title)
        self.category = QComboBox()
        self.category.addItem("— 请选择知识分类 —", None)
        if knowledge_service:
            for c in knowledge_service.categories.list(1000, order_by="sort_order ASC,id ASC"):
                self.category.addItem(c["name"], c["id"])
        self.category.setToolTip("没有合适的分类？请先到“知识库”页面新增分类，再回来保存。")
        form.addRow("保存名称（必填）", self.name)
        form.addRow("知识分类（必选）", self.category)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "缺少名称", "请填写保存名称，便于在知识库中识别。")
            return
        if self.require_all and self.category.currentData() is None:
            QMessageBox.warning(self, "请选择知识分类", "必须选择一个知识分类才能保存。\n"
                                                    "没有合适的分类？请先到“知识库”页面新增分类。")
            return
        self.accept()

    def data(self):
        return {
            "title": self.name.text().strip(),
            "category_id": self.category.currentData(),
            "category_name": self.category.currentText(),
        }


class CollectorResultDialog(QDialog):
    """采集结果详情窗体（左右布局）：
    左：原文 / 规整预览（可编辑）——「综合提示词规整」「扩写」「保存到知识库…」；
    右：提示词清单——用户手动点「获取提示词」后，模型分析左侧文字（按序号/标题/图片内容）拆分出多条提示词，
        可逐条扩写、勾选保存或一键保存全部。
    """

    def __init__(self, service, knowledge_service, model_service, task_manager, source_row, parent=None):
        super().__init__(parent)
        self.service = service
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.task_manager = task_manager
        self.source_row = source_row or {}
        self.source_id = self.source_row.get("id")
        self.setWindowTitle(f"采集结果详情 · 来源 #{self.source_id}")
        self.resize(1280, 820)
        self._organize_task = None
        self._extract_task = None
        self._expand_task = None
        self._organize_mode = "build"
        self._cards = []
        self._busy_started = None

        layout = QVBoxLayout(self)
        head = QLabel(f"标题：{self.source_row.get('title') or ''}    类型：{self.source_row.get('source_type') or ''}"
                      f"    时间：{(self.source_row.get('created_at') or '')[:19]}")
        head.setObjectName("sectionTitle")
        head.setWordWrap(True)
        layout.addWidget(head)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([620, 660])
        layout.addWidget(splitter, 1)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.elapsed_label = QLabel("")
        self.elapsed_label.setObjectName("panelHint")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.elapsed_label)
        layout.addLayout(progress_row)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self.status = QLabel("就绪：左侧为原文（可编辑），右侧点「获取提示词」让模型分析拆分。")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_progress)
            self.task_manager.task_finished.connect(self._on_finished)
            self.task_manager.task_failed.connect(self._on_failed)
        self._warm_up_model()

    def _warm_up_model(self):
        """后台预热：提前把模型加载进显存，用户点击时响应更快。"""
        if not (self.model_service and self.task_manager):
            return
        model = self.model_service.get_default("llm") or ""
        if not model:
            return
        provider = self.model_service.provider_for(model)
        from app.services.providers.ollama import OllamaProvider
        if not isinstance(provider, OllamaProvider):
            return  # API 供应商不需要"预加载进显存"，预热只会白跑一次请求、白花 token

        def worker(ctx):
            try:
                provider.generate("预热", model, options={"num_predict": 1})
            except Exception:
                pass
            return None
        self.task_manager.submit(fn=worker, task_type="modelcenter.warmup", input_data={"label": "预热模型"})

    # ---------- 左：原文预览（上） + 图片缩略图 + 综合提示词（下） ----------

    def _build_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        caption = QLabel("① 原文预览（可编辑，分析内容从这里提取）")
        caption.setObjectName("sectionTitle")
        layout.addWidget(caption)
        self.source_view = QTextEdit()
        try:
            data = self.service.load_source_content(self.source_id)
            self.source_view.setPlainText((data or {}).get("content") or "（该来源没有正文内容）")
        except Exception as exc:
            self.source_view.setPlainText(f"加载失败：{exc}")
        layout.addWidget(self.source_view, 3)

        self.image_strip = QWidget()
        self.image_strip_layout = QHBoxLayout(self.image_strip)
        self.image_strip_layout.setContentsMargins(0, 0, 0, 0)
        self.image_strip_layout.addStretch()
        self.image_strip.setVisible(False)
        layout.addWidget(self.image_strip)
        self._load_image_thumbnails()

        caption2 = QLabel("② 综合提示词（「综合提示词规整」的结果，可编辑/扩写后保存）")
        caption2.setObjectName("sectionTitle")
        layout.addWidget(caption2)
        self.summary_edit = QTextEdit()
        self.summary_edit.setPlaceholderText("点击下方「综合提示词规整」，把上方原文汇总成一条综合提示词显示在这里。")
        layout.addWidget(self.summary_edit, 2)

        row = QHBoxLayout()
        self.preview_llm_btn = QPushButton("综合提示词规整")
        self.preview_llm_btn.clicked.connect(lambda: self._organize_preview(use_llm=True))
        self.preview_expand_btn = QPushButton("扩写综合提示词")
        self.preview_expand_btn.clicked.connect(self._expand_preview)
        save_btn = QPushButton("保存到知识库…")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_summary_to_knowledge)
        for b in (self.preview_llm_btn, self.preview_expand_btn, save_btn):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        self.left_status = QLabel("提示：原文可直接编辑；点右侧「获取提示词」按原文（含图片内容）拆分。")
        self.left_status.setObjectName("panelHint")
        self.left_status.setWordWrap(True)
        layout.addWidget(self.left_status)
        return panel

    def _load_image_thumbnails(self):
        """把来源图片做成小缩略图嵌入原文下方，点击可放大查看。"""
        from PySide6.QtGui import QPixmap
        from pathlib import Path as _Path
        try:
            rows = self.service.images.list(6, 0, "source_id=?", (self.source_id,))
        except Exception:
            rows = []
        added = 0
        for row in rows:
            path = row.get("file_path") or ""
            if not path or not _Path(path).exists():
                continue
            pixmap = QPixmap(path)
            if pixmap.isNull():
                continue
            thumb = QLabel()
            thumb.setPixmap(pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
            thumb.setToolTip("点击放大查看")
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.mousePressEvent = (lambda event, p=path: self._open_image_preview(p))
            self.image_strip_layout.insertWidget(self.image_strip_layout.count() - 1, thumb)
            added += 1
        if added:
            hint = QLabel(f"（共 {added} 张图片，点击放大）")
            hint.setObjectName("panelHint")
            self.image_strip_layout.insertWidget(self.image_strip_layout.count() - 1, hint)
            self.image_strip.setVisible(True)

    def _open_image_preview(self, path):
        dialog = ImagePreviewDialog(path, self)
        dialog.exec()

    def _organize_preview(self, use_llm):
        if not self.service:
            return
        self._last_use_llm = use_llm
        if self._organize_task:
            self.left_status.setText("已有任务在执行。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        text = self.source_view.toPlainText().strip()
        if not self.task_manager:
            try:
                outcome = organizer.build_prompt_card(self.source_id, use_llm=use_llm, model_service=self.model_service)
                self._show_preview(outcome)
            except Exception as exc:
                self.left_status.setText(f"规整失败：{exc}")
            return
        model_service = self.model_service

        def worker(ctx):
            ctx.report_progress(10)
            outcome = organizer.expand_prompt(
                text, model_service,
                instruction="把下面的资料汇总成一条综合提示词（整合主体/环境/光线/构图/色彩/风格/质量要素），只输出提示词正文（英文），不要解释。",
                progress_cb=lambda chars: self._stream_progress(ctx, chars))
            ctx.report_progress(95)
            outcome["mode"] = "llm"
            return outcome

        self._organize_mode = "build"
        self._organize_task = self.task_manager.submit(
            fn=worker, task_type="collector.organize", input_data={"label": "综合提示词规整"})[0]
        self.left_status.setText("综合提示词规整中……")
        self._begin_busy("综合提示词规整")

    def _expand_preview(self):
        text = self.summary_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无内容", "请先点击「综合提示词规整」生成内容，或直接在②框中粘贴文字。")
            return
        if self._organize_task:
            self.left_status.setText("已有任务在执行。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.expand_prompt(text, self.model_service)
                self.summary_edit.setPlainText(outcome.get("text") or text)
                self.left_status.setText("综合提示词已扩写。")
                _offer_model_switch(self, outcome.get("hint"), self.left_status)
            except Exception as exc:
                self.left_status.setText(f"扩写暂不可用：{exc}")
            return
        model_service = self.model_service

        def worker(ctx):
            ctx.report_progress(10)
            outcome = organizer.expand_prompt(text, model_service,
                                              progress_cb=lambda chars: self._stream_progress(ctx, chars))
            ctx.report_progress(95)
            return outcome

        self._organize_mode = "expand"
        self._organize_task = self.task_manager.submit(
            fn=worker, task_type="collector.expand", input_data={"label": "扩写综合提示词"})[0]
        self.left_status.setText("综合提示词扩写中……")
        self._begin_busy("综合提示词扩写")

    def _show_preview(self, outcome):
        self.summary_edit.setPlainText(outcome.get("text") or "")
        self.left_status.setText("综合提示词已生成到下方②框中（可继续编辑或点「扩写综合提示词」完善）。")
        _offer_model_switch(self, (outcome or {}).get("hint"), self.left_status)

    def _save_summary_to_knowledge(self):
        text = self.summary_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无内容", "②框中没有可保存的综合提示词，请先点击「综合提示词规整」。")
            return
        if not self.knowledge_service:
            self.left_status.setText("知识库服务尚未初始化。")
            return
        dialog = SaveKnowledgeDialog(self.knowledge_service,
                                     default_title=self.source_row.get("title") or "", parent=self)
        if not dialog.exec():
            return
        data = dialog.data()
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        try:
            knowledge_id = organizer.save_summary_to_knowledge(
                self.source_id, text, title=data["title"], category_id=data["category_id"])
        except Exception as exc:
            self.left_status.setText(f"保存失败：{exc}")
            return
        self.left_status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")

    # ---------- 右：提示词清单（手动获取） ----------

    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        caption = QLabel("提示词清单（模型分析左侧文字后按序号/标题/图片逐条拆分）")
        caption.setObjectName("sectionTitle")
        layout.addWidget(caption)

        top_row = QHBoxLayout()
        self.fetch_btn = QPushButton("获取提示词（分析左侧文字）")
        self.fetch_btn.setObjectName("primary")
        self.fetch_btn.clicked.connect(self._manual_extract)
        top_row.addWidget(self.fetch_btn)
        self.extract_status = QLabel("尚未获取：点击左侧按钮，模型将读取文字内容并拆分出不同类型的提示词。")
        self.extract_status.setObjectName("panelHint")
        self.extract_status.setWordWrap(True)
        top_row.addWidget(self.extract_status, 1)
        layout.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_host)
        layout.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选 / 全不选")
        self.select_all_btn.clicked.connect(self._toggle_all)
        self.expand_btn = QPushButton("大模型扩写选中项")
        self.expand_btn.setEnabled(False)
        self.expand_btn.clicked.connect(self._expand_selected)
        self.save_all_btn = QPushButton("一键保存全部")
        self.save_all_btn.setEnabled(False)
        self.save_all_btn.clicked.connect(lambda: self._save(only_checked=False))
        self.save_sel_btn = QPushButton("保存选中到知识库")
        self.save_sel_btn.setEnabled(False)
        self.save_sel_btn.clicked.connect(lambda: self._save(only_checked=True))
        for b in (self.select_all_btn, self.expand_btn, self.save_all_btn, self.save_sel_btn):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        return panel

    def _manual_extract(self):
        """用户手动触发：把左侧预览框当前文字交给模型拆分。"""
        if self._extract_task:
            self.extract_status.setText("正在获取中，请稍候……")
            return
        text = self.source_view.toPlainText().strip()
        if not text:
            self.extract_status.setText("上方原文预览没有文字，请先填入内容。")
            return
        for card in self._cards:
            card["check"].parent()  # 保留控件生命周期
        self._clear_cards()
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        model_service = self.model_service
        self.extract_status.setText("正在分析原文（含图片内容）并拆分提示词……")
        self.fetch_btn.setEnabled(False)
        if not self.task_manager:
            try:
                outcome = organizer.extract_prompts_from_text(text, model_service, source_id=self.source_id)
                self._fill_cards(outcome)
            except Exception as exc:
                self._handle_extract_error(str(exc))
            finally:
                self.fetch_btn.setEnabled(True)
            return

        def worker(ctx):
            ctx.report_progress(5)
            outcome = organizer.extract_prompts_from_text(
                text, model_service, source_id=self.source_id,
                progress_cb=lambda value: ctx.report_progress(max(5.0, min(95.0, float(value)))))
            ctx.report_progress(95)
            return outcome

        self._extract_task = self.task_manager.submit(
            fn=worker, task_type="collector.extract", input_data={"label": "提示词拆分"})[0]
        self._begin_busy("正在拆分提示词")

    def _clear_cards(self):
        for card in self._cards:
            widget = card["check"].parentWidget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = []

    def _fill_cards(self, outcome):
        items = outcome.get("items") or []
        if not items:
            self.extract_status.setText("未拆分到提示词：可编辑原文后重试（若模型输出无结构，可换更强的模型或缩短原文）。")
            return
        for item in items:
            self._add_card(item)
        chunks = outcome.get("chunks") or 1
        ocr_n = outcome.get("ocr_images") or 0
        model = outcome.get("model") or ""
        ocr_model = outcome.get("ocr_model") or ""
        note = f"（原文分 {chunks} 段分析" + (f"，含 {ocr_n} 张图片内容" if ocr_n else "")                + (f"，分析模型：{model}" if model else "")                + (f"，图片识别模型：{ocr_model}" if ocr_n and ocr_model else "") + "）"
        self.extract_status.setText(
            f"已拆分出 {len(items)} 条提示词{note}；可逐条编辑、扩写或保存（重复保存自动覆盖旧记录）。")
        for b in (self.expand_btn, self.save_all_btn, self.save_sel_btn):
            b.setEnabled(True)

    def _add_card(self, entry):
        card = QFrame()
        card.setProperty("card", True)
        box = QVBoxLayout(card)
        top = QHBoxLayout()
        check = QCheckBox("提示词")
        check.setChecked(True)
        top.addWidget(check)
        title = QLineEdit(entry.get("title") or "提示词")
        title.setPlaceholderText("名称（保存到知识库用）")
        title.setMaximumWidth(230)
        top.addWidget(title)
        top.addWidget(QLabel("分类"))
        combo = QComboBox()
        for name in self._available_categories():
            combo.addItem(name, name)
        current = entry.get("category") or "其他"
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else combo.count() - 1)
        combo.setMaximumWidth(130)
        top.addWidget(combo)
        top.addStretch()
        box.addLayout(top)
        edit = QTextEdit()
        edit.setPlainText(entry.get("prompt") or "")
        edit.setMinimumHeight(82)
        edit.setMaximumHeight(140)
        box.addWidget(edit)
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self._cards.append({"check": check, "title": title, "category": combo, "prompt": edit})

    def _available_categories(self):
        from app.services.keyword_organize_service import KeywordOrganizeService
        names = []
        if self.knowledge_service:
            for c in self.knowledge_service.categories.list(1000, order_by="sort_order ASC,id ASC"):
                if c.get("parent_id") is None and c["name"] in KeywordOrganizeService.PROMPT_CATEGORIES:
                    names.append(c["name"])
        for name in KeywordOrganizeService.PROMPT_CATEGORIES:
            if name not in names:
                names.append(name)
        return names

    def _toggle_all(self):
        target = not all(c["check"].isChecked() for c in self._cards)
        for card in self._cards:
            card["check"].setChecked(target)

    def _expand_selected(self):
        target_cards = [c for c in self._cards if c["check"].isChecked() and c["prompt"].toPlainText().strip()]
        if not target_cards:
            QMessageBox.information(self, "未选择", "请先勾选要扩写的提示词。")
            return
        if self._expand_task:
            self.extract_status.setText("已有扩写任务在执行。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        model_service = self.model_service
        texts = [c["prompt"].toPlainText() for c in target_cards[:8]]
        if not self.task_manager:
            try:
                for card, text in zip(target_cards, texts):
                    last_hint = ""
                    for card, text in zip(target_cards, texts):
                        outcome = organizer.expand_prompt(text, model_service)
                        card["prompt"].setPlainText(outcome.get("text") or text)
                        last_hint = outcome.get("hint") or last_hint
                self.extract_status.setText(f"已扩写 {len(texts)} 条提示词。")
                _offer_model_switch(self, last_hint, self.extract_status)
            except Exception as exc:
                self._handle_extract_error(str(exc))
            return

        def worker(ctx):
            results = []
            hint = ""
            span = 85.0 / max(1, len(texts))
            for i, text in enumerate(texts):
                base = 10.0 + i * span
                outcome = organizer.expand_prompt(
                    text, model_service,
                    progress_cb=lambda chars, b=base: ctx.report_progress(min(b + span, 5.0 + chars / 40.0 + b / 10.0)))
                results.append(outcome.get("text") or text)
                if outcome.get("hint") and not hint:
                    hint = outcome.get("hint")
            return {"texts": results, "hint": hint}

        self._expand_task = self.task_manager.submit(
            fn=worker, task_type="collector.expand", input_data={"label": "扩写"})[0]
        self.extract_status.setText(f"正在扩写 {len(texts)} 条提示词……")
        self._begin_busy("扩写提示词")

    def _save(self, only_checked=True):
        cards = [c for c in self._cards if (c["check"].isChecked() or not only_checked) and c["prompt"].toPlainText().strip()]
        if not cards:
            QMessageBox.information(self, "未选择", "没有可保存的提示词。")
            return
        if not self.knowledge_service:
            self.extract_status.setText("知识库服务尚未初始化。")
            return
        entries = [{"title": c["title"].text().strip() or "提示词",
                    "category": c["category"].currentData(),
                    "prompt": c["prompt"].toPlainText().strip()} for c in cards]
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        category_id_by_name = {}
        for row in self.knowledge_service.categories.list(1000):
            if row.get("parent_id") is None and row["name"] in KeywordOrganizeService.PROMPT_CATEGORIES:
                category_id_by_name.setdefault(row["name"], row["id"])
        try:
            outcome = organizer.save_extracted_prompts(self.source_id, entries, category_id_by_name, overwrite=True)
        except Exception as exc:
            self.extract_status.setText(f"保存失败：{exc}")
            return
        by_cat = "、".join(f"{k}×{v}" for k, v in (outcome.get("by_category") or {}).items())
        msg = f"已保存 {outcome['saved']} 条提示词到知识库（{by_cat}）"
        if outcome.get("overwritten"):
            msg += f"，并覆盖了此前的 {outcome['overwritten']} 条旧记录"
        msg += "。"
        self.extract_status.setText(msg)
        QMessageBox.information(self, "保存完成", msg)

    # ---------- 进度与时长 ----------

    def _begin_busy(self, text="处理中"):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(2)
        import time as _time
        self._time = _time
        self._busy_started = _time.time()
        self.elapsed_label.setText(f"{text}…已用时 0s")
        self._elapsed_timer.start()

    def _end_busy(self):
        self._elapsed_timer.stop()
        self._busy_started = None
        self.progress_bar.setVisible(False)
        self.elapsed_label.setText("")

    def _tick_elapsed(self):
        if self._busy_started is not None:
            used = int(self._time.time() - self._busy_started)
            current = self.elapsed_label.text().split("已用时")[0]
            self.elapsed_label.setText(f"{current}已用时 {used}s")

    @staticmethod
    def _stream_progress(ctx, chars):
        ctx.report_progress(min(95.0, 5.0 + chars / 40.0))

    # ---------- 任务回调 ----------

    def _on_progress(self, task_id, value):
        if task_id == self._organize_task:
            self.left_status.setText(f"处理中……{value:.0f}%")
            self.progress_bar.setValue(int(value))
        elif task_id == self._extract_task:
            self.extract_status.setText(f"正在分析左侧文字并拆分提示词……{value:.0f}%")
            self.progress_bar.setValue(int(value))
        elif task_id == self._expand_task:
            self.extract_status.setText(f"正在扩写提示词……{value:.0f}%")
            self.progress_bar.setValue(int(value))

    def _on_finished(self, task_id, outcome):
        if task_id in (self._organize_task, self._extract_task, self._expand_task):
            self._end_busy()
        if task_id == self._organize_task:
            self._organize_task = None
            if self._organize_mode == "expand":
                self.summary_edit.setPlainText((outcome or {}).get("text") or self.summary_edit.toPlainText())
                self.left_status.setText("综合提示词已扩写（可继续编辑后保存）。")
            else:
                self._show_preview(outcome)
            _offer_model_switch(self, (outcome or {}).get("hint"), self.left_status)
        elif task_id == self._extract_task:
            self._extract_task = None
            self.fetch_btn.setEnabled(True)
            self._fill_cards(outcome)
        elif task_id == self._expand_task:
            self._expand_task = None
            data = outcome if isinstance(outcome, dict) else {}
            texts = data.get("texts") or []
            target_cards = [c for c in self._cards if c["check"].isChecked() and c["prompt"].toPlainText().strip()][:8]
            for card, text in zip(target_cards, texts):
                if text:
                    card["prompt"].setPlainText(text)
            self.extract_status.setText(f"已扩写 {len(texts)} 条提示词（可继续编辑后保存）。")
            _offer_model_switch(self, data.get("hint"), self.extract_status)

    def _handle_extract_error(self, message):
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.extract_status.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        self.extract_status.setText(f"操作失败：{message}")

    def _on_failed(self, task_id, message):
        if task_id in (self._organize_task, self._extract_task, self._expand_task):
            self._end_busy()
        if task_id == self._extract_task:
            self._extract_task = None
            self.fetch_btn.setEnabled(True)
        if task_id == self._organize_task:
            self._organize_task = None
        if task_id == self._expand_task:
            self._expand_task = None
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.extract_status.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        self.extract_status.setText(f"任务失败：{message}")

    def closeEvent(self, event):
        if self.task_manager:
            for signal in (self.task_manager.task_progress, self.task_manager.task_finished, self.task_manager.task_failed):
                for slot in (self._on_progress, self._on_finished, self._on_failed):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        super().closeEvent(event)


class ImagePreviewDialog(QDialog):
    """图片放大预览：点击缩略图后用滚轮区域查看原图。"""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QPixmap
        from pathlib import Path as _Path
        self.setWindowTitle(f"图片预览 · {_Path(str(image_path)).name}")
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            label.setText("图片无法加载")
        else:
            screen = self.screen().availableGeometry() if self.screen() else None
            max_w = int((screen.width() if screen else 1280) * 0.9)
            max_h = int((screen.height() if screen else 800) * 0.9)
            shown = pixmap if pixmap.width() <= max_w and pixmap.height() <= max_h else pixmap.scaled(
                max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(shown)
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(btn)
        layout.addLayout(row)
        if self.parent() is not None:
            self.resize(int(self.parent().width() * 0.85), int(self.parent().height() * 0.85))
