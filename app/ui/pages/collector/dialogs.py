from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QDialogButtonBox, QTextEdit, QPushButton, QMessageBox, QFrame,
    QTabWidget, QWidget, QScrollArea, QCheckBox,
)


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
    """采集结果详情窗体：
    ① 规整预览页：AI/关键词规整 → 预览编辑 → 选分类保存；
    ② 多风格识别页（自动）：打开即自动分析是否含多种提示词风格，分类展示供勾选保存。
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
        self.resize(1000, 780)
        self._organize_task = None
        self._style_task = None
        self._style_cards = []
        self._saved = False

        layout = QVBoxLayout(self)
        head = QLabel(f"标题：{self.source_row.get('title') or ''}    类型：{self.source_row.get('source_type') or ''}"
                      f"    时间：{(self.source_row.get('created_at') or '')[:19]}")
        head.setObjectName("sectionTitle")
        head.setWordWrap(True)
        layout.addWidget(head)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_organize_tab(), "规整预览")
        self.tabs.addTab(self._build_styles_tab(), "多风格识别（自动）")

        self.status = QLabel("就绪")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_progress)
            self.task_manager.task_finished.connect(self._on_finished)
            self.task_manager.task_failed.connect(self._on_failed)
        self._start_style_detection()

    # ---------- 页①：规整预览 ----------

    def _build_organize_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        try:
            data = self.service.load_source_content(self.source_id)
            self.detail.setPlainText((data or {}).get("content") or "（该来源没有正文内容）")
        except Exception as exc:
            self.detail.setPlainText(f"加载失败：{exc}")
        layout.addWidget(self.detail, 2)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); layout.addWidget(sep)
        btn_row = QHBoxLayout()
        self.preview_llm_btn = QPushButton("规整为图片/视频提示词（AI）")
        self.preview_llm_btn.clicked.connect(lambda: self._organize_preview(use_llm=True))
        self.preview_kw_btn = QPushButton("基础骨架规整")
        self.preview_kw_btn.clicked.connect(lambda: self._organize_preview(use_llm=False))
        self.re_run_btn = QPushButton("重新规整")
        self.re_run_btn.clicked.connect(lambda: self._organize_preview(getattr(self, "_last_use_llm", True)))
        save_btn = QPushButton("保存到知识库…")
        save_btn.clicked.connect(self._save_summary_to_knowledge)
        for b in (self.preview_llm_btn, self.preview_kw_btn, self.re_run_btn, save_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        preview_label = QLabel("规整预览（可编辑，确认满意后保存到知识库）")
        preview_label.setObjectName("sectionTitle")
        layout.addWidget(preview_label)
        self.preview = QTextEdit()
        self.preview.setPlaceholderText(
            "点击“规整为图片/视频提示词（AI）”或“基础骨架规整”后，结果会显示在这里；\n"
            "可直接编辑，满意后点“保存到知识库…”，选择知识分类与名称即可入库。")
        layout.addWidget(self.preview, 3)
        return page

    def _organize_preview(self, use_llm):
        if not self.service:
            return
        self._last_use_llm = use_llm
        if self._organize_task:
            self.status.setText("已有规整任务在执行。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.build_prompt_card(self.source_id, use_llm=use_llm, model_service=self.model_service)
                self._show_preview(outcome)
            except Exception as exc:
                self.status.setText(f"规整失败：{exc}")
            return
        model_service = self.model_service

        def worker(ctx):
            ctx.report_progress(30)
            outcome = organizer.build_prompt_card(self.source_id, use_llm=use_llm, model_service=model_service, use_ocr=True)
            ctx.report_progress(95)
            return outcome

        self._organize_task = self.task_manager.submit(
            fn=worker, task_type="collector.organize", input_data={"label": "规整预览"})[0]
        self.status.setText("规整中……")

    def _show_preview(self, outcome):
        self.preview.setPlainText(outcome.get("text") or "")
        if outcome.get("mode") == "llm":
            self.status.setText(f"已规整为图片/视频提示词卡（模型：{outcome.get('model')}）；可编辑后点“保存到知识库…”。")
        else:
            self.status.setText("已生成基础提示词骨架；连接默认模型后可重新规整为完整提示词。")

    def _save_summary_to_knowledge(self):
        text = self.preview.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无内容", "请先点击“规整为图片/视频提示词（AI）”或“基础骨架规整”生成预览内容。")
            return
        if not self.knowledge_service:
            self.status.setText("知识库服务尚未初始化。")
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
            self.status.setText(f"保存失败：{exc}")
            return
        self._saved = True
        self.status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")

    # ---------- 页②：多风格识别（自动） ----------

    def _build_styles_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.style_status = QLabel("正在自动分析资料中的提示词风格……")
        self.style_status.setObjectName("panelHint")
        self.style_status.setWordWrap(True)
        layout.addWidget(self.style_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.style_host = QWidget()
        self.style_layout = QVBoxLayout(self.style_host)
        self.style_layout.addStretch()
        scroll.setWidget(self.style_host)
        layout.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.style_select_btn = QPushButton("全选 / 全不选")
        self.style_select_btn.clicked.connect(self._toggle_all_styles)
        self.style_save_btn = QPushButton("保存选中风格到知识库…")
        self.style_save_btn.setObjectName("primary")
        self.style_save_btn.setEnabled(False)
        self.style_save_btn.clicked.connect(self._save_selected_styles)
        row.addWidget(self.style_select_btn)
        row.addWidget(self.style_save_btn)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _start_style_detection(self):
        if not self.service or self.source_id is None:
            self.style_status.setText("没有可分析的来源。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.detect_styles(self.source_id, self.model_service)
                self._fill_styles(outcome)
            except Exception as exc:
                self.style_status.setText(f"风格识别暂不可用：{exc}")
            return
        model_service = self.model_service

        def worker(ctx):
            ctx.report_progress(30)
            outcome = organizer.detect_styles(self.source_id, model_service)
            ctx.report_progress(95)
            return outcome

        self._style_task = self.task_manager.submit(
            fn=worker, task_type="collector.styles", input_data={"label": "多风格识别"})[0]

    def _fill_styles(self, outcome):
        styles = outcome.get("styles") or []
        if not styles:
            self.style_status.setText("未识别到风格（可在模型中心设置默认模型后重试）。")
            return
        if len(styles) == 1:
            self.style_status.setText(
                f"未发现多种风格（仅识别到一种：{styles[0].get('style')}）。如需保存，勾选后点击下方按钮。")
        else:
            self.style_status.setText(
                f"共识别到 {len(styles)} 种提示词风格，已分类展示；勾选需要的风格后保存到知识库：")
        for item in styles:
            self._add_style_card(item.get("style") or "风格", item.get("prompt") or "")
        self.style_save_btn.setEnabled(True)

    def _add_style_card(self, style, prompt):
        card = QFrame()
        card.setProperty("card", True)
        box = QVBoxLayout(card)
        row = QHBoxLayout()
        check = QCheckBox(f"⭐ {style}")
        check.setChecked(True)
        row.addWidget(check)
        row.addStretch()
        box.addLayout(row)
        edit = QTextEdit()
        edit.setPlainText(prompt)
        edit.setMinimumHeight(92)
        edit.setMaximumHeight(140)
        box.addWidget(edit)
        self.style_layout.insertWidget(self.style_layout.count() - 1, card)
        self._style_cards.append((check, style, edit))

    def _toggle_all_styles(self):
        target = not all(c[0].isChecked() for c in self._style_cards)
        for check, _s, _e in self._style_cards:
            check.setChecked(target)

    def _save_selected_styles(self):
        selected = [(s, e.toPlainText().strip()) for c, s, e in self._style_cards
                    if c.isChecked() and e.toPlainText().strip()]
        if not selected:
            QMessageBox.information(self, "未选择", "请至少勾选一种风格并保留提示词内容。")
            return
        if not self.knowledge_service:
            self.style_status.setText("知识库服务尚未初始化。")
            return
        dialog = SaveKnowledgeDialog(self.knowledge_service,
                                     default_title=self.source_row.get("title") or "多风格提示词", parent=self)
        if not dialog.exec():
            self.style_status.setText("已取消保存（保存到知识库需要选择分类与名称）。")
            return
        data = dialog.data()
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        saved, failed = 0, []
        for style, prompt in selected:
            try:
                organizer.knowledge.create({
                    "source_type": "multi_style", "source_id": self.source_id,
                    "title": f"{data['title']} · {style}"[:120],
                    "content": prompt,
                    "summary": f"关键词：多风格识别 | {style}",
                    "category_id": data["category_id"],
                    "knowledge_type": "prompt",
                    "confidence": 1.0,
                })
                saved += 1
            except Exception as exc:
                failed.append(f"{style}: {exc}")
        msg = f"已保存 {saved} 种风格到知识库「{data['category_name']}」分类下。"
        if failed:
            msg += " 失败：" + "；".join(failed[:3])
        self.style_status.setText(msg)
        QMessageBox.information(self, "保存完成", msg)

    # ---------- 任务回调 ----------

    def _on_progress(self, task_id, value):
        if task_id == self._organize_task:
            self.status.setText(f"规整中……{value:.0f}%")
        elif task_id == self._style_task:
            self.style_status.setText(f"正在自动分析资料中的提示词风格……{value:.0f}%")

    def _on_finished(self, task_id, outcome):
        if task_id == self._organize_task:
            self._organize_task = None
            self._show_preview(outcome)
        elif task_id == self._style_task:
            self._style_task = None
            self._fill_styles(outcome)

    def _on_failed(self, task_id, message):
        if task_id == self._organize_task:
            self._organize_task = None
            self.status.setText(f"规整失败：{message}")
        elif task_id == self._style_task:
            self._style_task = None
            self.style_status.setText(f"风格识别暂不可用：{message}")

    def closeEvent(self, event):
        if self.task_manager:
            for signal in (self.task_manager.task_progress, self.task_manager.task_finished, self.task_manager.task_failed):
                for slot in (self._on_progress, self._on_finished, self._on_failed):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        super().closeEvent(event)
