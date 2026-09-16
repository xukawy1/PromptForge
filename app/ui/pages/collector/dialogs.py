from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QDialogButtonBox, QTextEdit, QPushButton, QMessageBox, QFrame,
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
    """采集结果详情窗体：结果详情 + AI 规整/关键词规整（预览）+ 保存到知识库（选分类）。"""

    def __init__(self, service, knowledge_service, model_service, task_manager, source_row, parent=None):
        super().__init__(parent)
        self.service = service
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.task_manager = task_manager
        self.source_row = source_row or {}
        self.source_id = self.source_row.get("id")
        self.setWindowTitle(f"采集结果详情 · 来源 #{self.source_id}")
        self.resize(960, 720)
        self._organize_task = None
        self._saved = False

        layout = QVBoxLayout(self)
        head = QLabel(f"标题：{self.source_row.get('title') or ''}    类型：{self.source_row.get('source_type') or ''}"
                      f"    时间：{(self.source_row.get('created_at') or '')[:19]}")
        head.setObjectName("sectionTitle")
        head.setWordWrap(True)
        layout.addWidget(head)
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
        save_btn.clicked.connect(self._save_to_knowledge)
        btn_row.addWidget(self.preview_llm_btn)
        btn_row.addWidget(self.preview_kw_btn)
        btn_row.addWidget(self.re_run_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        preview_label = QLabel("规整预览（可编辑，确认满意后保存到知识库）")
        preview_label.setObjectName("sectionTitle")
        layout.addWidget(preview_label)
        self.preview = QTextEdit()
        self.preview.setPlaceholderText(
            "点击“AI 规整”或“关键词规整”后，规整结果会显示在这里；\n"
            "你可以直接编辑，满意后点“保存到知识库…”，选择知识分类与名称即可入库。")
        layout.addWidget(self.preview, 3)

        self.status = QLabel("就绪")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_progress)
            self.task_manager.task_finished.connect(self._on_finished)
            self.task_manager.task_failed.connect(self._on_failed)

    # ---- 规整预览 ----

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
        mode = outcome.get("mode")
        if mode == "llm":
            self.status.setText(f"已规整为图片/视频提示词卡（模型：{outcome.get('model')}）；可编辑后点“保存到知识库…”。")
        else:
            self.status.setText("已生成基础提示词骨架；连接默认 LLM 后可重新规整为完整提示词。")

    def _on_progress(self, task_id, value):
        if task_id == self._organize_task:
            self.status.setText(f"规整中……{value:.0f}%")

    def _on_finished(self, task_id, outcome):
        if task_id == self._organize_task:
            self._organize_task = None
            self._show_preview(outcome)

    def _on_failed(self, task_id, message):
        if task_id == self._organize_task:
            self._organize_task = None
            self.status.setText(f"规整失败：{message}")

    # ---- 保存 ----

    def _save_to_knowledge(self):
        text = self.preview.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无内容", "请先点击“AI 规整”或“关键词规整”生成预览内容。")
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
        self.status.setText(f"✅ 已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")

    def closeEvent(self, event):
        if self.task_manager:
            try:
                self.task_manager.task_progress.disconnect(self._on_progress)
                self.task_manager.task_finished.disconnect(self._on_finished)
                self.task_manager.task_failed.disconnect(self._on_failed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)


class MultiStyleDialog(QDialog):
    """多种提示词风格识别结果窗体：每个风格一张卡片，勾选后统一选分类保存到知识库。"""

    def __init__(self, service, knowledge_service, model_service, task_manager, source_row, parent=None):
        super().__init__(parent)
        self.service = service
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.task_manager = task_manager
        self.source_row = source_row or {}
        self.source_id = self.source_row.get("id")
        self.cards = []
        self._task_id = None
        self.setWindowTitle(f"识别到的提示词风格 · 来源 #{self.source_id}")
        self.resize(900, 760)

        layout = QVBoxLayout(self)
        head = QLabel(f"来源：{self.source_row.get('title') or ''}")
        head.setObjectName("sectionTitle")
        head.setWordWrap(True)
        layout.addWidget(head)
        self.status = QLabel("正在分析资料中的提示词风格……")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.addStretch()
        scroll.setWidget(self.cards_host)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选 / 全不选")
        self.select_all_btn.clicked.connect(self._toggle_all)
        self.save_btn = QPushButton("保存选中风格到知识库…")
        self.save_btn.setObjectName("primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_selected)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_progress)
            self.task_manager.task_finished.connect(self._on_finished)
            self.task_manager.task_failed.connect(self._on_failed)
        self._start()

    def _start(self):
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.detect_styles(self.source_id, self.model_service)
                self._fill(outcome)
            except Exception as exc:
                self.status.setText(f"识别失败：{exc}")
            return

        def worker(ctx):
            ctx.report_progress(30)
            outcome = organizer.detect_styles(self.source_id, self.model_service)
            ctx.report_progress(95)
            return outcome

        self._task_id = self.task_manager.submit(fn=worker, task_type="collector.styles",
                                                 input_data={"label": "多风格识别"})[0]

    def _on_progress(self, task_id, value):
        if task_id == self._task_id:
            self.status.setText(f"正在分析资料中的提示词风格……{value:.0f}%")

    def _on_finished(self, task_id, outcome):
        if task_id == self._task_id:
            self._task_id = None
            self._fill(outcome)

    def _on_failed(self, task_id, message):
        if task_id == self._task_id:
            self._task_id = None
            self.status.setText(f"识别失败：{message}")

    def _fill(self, outcome):
        styles = outcome.get("styles") or []
        if not styles:
            self.status.setText("未识别到风格，可稍后重试（需在模型中心设置默认 LLM）。")
            return
        note = "（模型未按 JSON 输出，已作为单一风格展示）" if outcome.get("fallback") else ""
        self.status.setText(f"共识别到 {len(styles)} 种提示词风格{note}，勾选需要的风格后保存：")
        for item in styles:
            self._add_card(item.get("style") or "风格", item.get("prompt") or "")
        self.save_btn.setEnabled(True)

    def _add_card(self, style, prompt):
        from PySide6.QtWidgets import QCheckBox
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
        edit.setMinimumHeight(96)
        edit.setMaximumHeight(150)
        box.addWidget(edit)
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.cards.append((check, style, edit))

    def _toggle_all(self):
        target = not all(c[0].isChecked() for c in self.cards)
        for check, _s, _e in self.cards:
            check.setChecked(target)

    def _save_selected(self):
        selected = [(s, e.toPlainText().strip()) for c, s, e in self.cards if c.isChecked() and e.toPlainText().strip()]
        if not selected:
            QMessageBox.information(self, "未选择", "请至少勾选一种风格并保留提示词内容。")
            return
        if not self.knowledge_service:
            self.status.setText("知识库服务尚未初始化。")
            return
        dialog = SaveKnowledgeDialog(self.knowledge_service, default_title=self.source_row.get("title") or "多风格提示词", parent=self)
        if not dialog.exec():
            self.status.setText("已取消保存（保存到知识库需要选择分类与名称）。")
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
        self.status.setText(msg)
        QMessageBox.information(self, "保存完成", msg)

    def closeEvent(self, event):
        if self.task_manager:
            try:
                self.task_manager.task_progress.disconnect(self._on_progress)
                self.task_manager.task_finished.disconnect(self._on_finished)
                self.task_manager.task_failed.disconnect(self._on_failed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)
