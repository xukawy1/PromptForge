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
    ① 提示词清单（自动）：打开即自动把内容拆分成「综合总结提示词 + 多个分散提示词」，
       每张卡片可按类别归档保存；支持大模型扩写选中项、一键保存全部；
    ② 规整预览：AI/关键词规整 → 预览编辑 → 保存。
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
        self.resize(1020, 820)
        self._organize_task = None
        self._extract_task = None
        self._expand_task = None
        self._organize_mode = "build"
        self._cards = []
        self._category_combos = []

        layout = QVBoxLayout(self)
        head = QLabel(f"标题：{self.source_row.get('title') or ''}    类型：{self.source_row.get('source_type') or ''}"
                      f"    时间：{(self.source_row.get('created_at') or '')[:19]}")
        head.setObjectName("sectionTitle")
        head.setWordWrap(True)
        layout.addWidget(head)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_prompt_list_tab(), "提示词清单（自动）")
        self.tabs.addTab(self._build_organize_tab(), "规整预览")

        from PySide6.QtWidgets import QProgressBar
        import time as _time
        self._time = _time
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
        self._busy_started = None
        from PySide6.QtCore import QTimer
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self.status = QLabel("就绪")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_progress)
            self.task_manager.task_finished.connect(self._on_finished)
            self.task_manager.task_failed.connect(self._on_failed)
        self._start_extract()

    # ---------- 进度与时长 ----------

    def _begin_busy(self, text="处理中"):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(2)
        self._busy_started = self._time.time()
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
        # 按已生成字符数推进进度（最高 95%），让用户看到实时进展。
        ctx.report_progress(min(95.0, 5.0 + chars / 40.0))

    # ---------- 页①：提示词清单（自动拆分） ----------

    def _build_prompt_list_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.extract_status = QLabel("正在自动拆分资料中的提示词（综合总结 + 分散提示词）……")
        self.extract_status.setObjectName("panelHint")
        self.extract_status.setWordWrap(True)
        layout.addWidget(self.extract_status)

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
        self.save_sel_btn.setObjectName("primary")
        self.save_sel_btn.setEnabled(False)
        self.save_sel_btn.clicked.connect(lambda: self._save(only_checked=True))
        for b in (self.select_all_btn, self.expand_btn, self.save_all_btn, self.save_sel_btn):
            row.addWidget(b)
        row.addStretch()
        layout.addLayout(row)
        return page

    def _start_extract(self):
        if not self.service or self.source_id is None:
            self.extract_status.setText("没有可分析的来源。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.extract_prompts(self.source_id, self.model_service)
                self._fill_cards(outcome)
            except Exception as exc:
                self.extract_status.setText(f"自动拆分暂不可用：{exc}")
            return
        model_service = self.model_service

        def worker(ctx):
            ctx.report_progress(10)
            outcome = organizer.extract_prompts(
                self.source_id, model_service,
                progress_cb=lambda chars: self._stream_progress(ctx, chars))
            ctx.report_progress(95)
            return outcome

        self._extract_task = self.task_manager.submit(
            fn=worker, task_type="collector.extract", input_data={"label": "提示词拆分"})[0]
        self._begin_busy("正在拆分提示词")

    def _fill_cards(self, outcome):
        summary = outcome.get("summary") or {}
        items = outcome.get("items") or []
        if not summary and not items:
            self.extract_status.setText("未拆分到提示词（可在模型中心设置默认模型后重试）。")
            return
        for item in items:
            self._add_card(item, is_summary=False)
        note = "（模型输出未完全结构化，已尽力拆分）" if outcome.get("fallback") else ""
        summary_text = ((summary or {}).get("prompt") or "").strip()
        if summary_text:
            self.preview.setPlainText(summary_text)
        self.extract_status.setText(
            f"已拆分出 {len(items)} 条分散提示词（各自命名/分类，可逐条扩写或保存）{note}；"
            "综合提示词已生成到「规整预览」页，可扩写后保存。"
            "重复导入同一网页会自动覆盖旧记录。")
        for b in (self.expand_btn, self.save_all_btn, self.save_sel_btn):
            b.setEnabled(True)

    def _add_card(self, entry, is_summary=False):
        card = QFrame()
        card.setProperty("card", True)
        box = QVBoxLayout(card)
        top = QHBoxLayout()
        check = QCheckBox("综合总结提示词" if is_summary else "提示词")
        check.setChecked(True)
        top.addWidget(check)
        title = QLineEdit(entry.get("title") or ("综合总结" if is_summary else "提示词"))
        title.setPlaceholderText("名称（保存到知识库用）")
        title.setMaximumWidth(240)
        top.addWidget(title)
        top.addWidget(QLabel("分类"))
        combo = QComboBox()
        for name in self._available_categories():
            combo.addItem(name, name)
        current = entry.get("category") or ("风格" if is_summary else "其他")
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else combo.count() - 1)
        combo.setMaximumWidth(140)
        top.addWidget(combo)
        top.addStretch()
        box.addLayout(top)
        edit = QTextEdit()
        edit.setPlainText(entry.get("prompt") or "")
        edit.setMinimumHeight(86)
        edit.setMaximumHeight(150)
        box.addWidget(edit)
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self._cards.append({"check": check, "title": title, "category": combo, "prompt": edit, "summary": is_summary})
        self._category_combos.append(combo)

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
        if not self.task_manager:
            try:
                for card in target_cards[:8]:
                    outcome = organizer.expand_prompt(card["prompt"].toPlainText(), self.model_service)
                    card["prompt"].setPlainText(outcome.get("text") or card["prompt"].toPlainText())
                self.extract_status.setText(f"已扩写 {len(target_cards[:8])} 条提示词。")
            except Exception as exc:
                self.extract_status.setText(f"扩写暂不可用：{exc}")
            return
        model_service = self.model_service
        texts = [c["prompt"].toPlainText() for c in target_cards[:8]]

        def worker(ctx):
            results = []
            span = 85.0 / max(1, len(texts))
            for i, text in enumerate(texts):
                base = 10.0 + i * span
                outcome = organizer.expand_prompt(
                    text, model_service,
                    progress_cb=lambda chars, b=base: ctx.report_progress(min(b + span * 0.9, 5.0 + chars / 40.0 + b / 10.0)))
                results.append(outcome.get("text") or text)
            return results

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
        if self.knowledge_service:
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

    # ---------- 页②：规整预览 ----------

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
        self.preview_llm_btn = QPushButton("综合提示词规整")
        self.preview_llm_btn.clicked.connect(lambda: self._organize_preview(use_llm=True))
        self.preview_expand_btn = QPushButton("扩写综合提示词")
        self.preview_expand_btn.clicked.connect(self._expand_preview)
        save_btn = QPushButton("保存到知识库…")
        save_btn.clicked.connect(self._save_summary_to_knowledge)
        for b in (self.preview_llm_btn, self.preview_expand_btn, save_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        preview_label = QLabel("综合提示词（可编辑/扩写，确认满意后保存到知识库）")
        preview_label.setObjectName("sectionTitle")
        layout.addWidget(preview_label)
        self.preview = QTextEdit()
        self.preview.setPlaceholderText(
            "打开页面时会自动把网页内容汇总成一条综合提示词显示在这里；\n"
            "可点击“综合提示词规整”重新生成、“扩写综合提示词”让大模型扩写完善；\n"
            "满意后点“保存到知识库…”，选择知识分类与名称即可入库。")
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
            ctx.report_progress(10)
            outcome = organizer.build_prompt_card(
                self.source_id, use_llm=use_llm, model_service=model_service, use_ocr=True,
                progress_cb=lambda chars: self._stream_progress(ctx, chars))
            ctx.report_progress(95)
            return outcome

        self._organize_mode = "build"
        self._organize_task = self.task_manager.submit(
            fn=worker, task_type="collector.organize", input_data={"label": "综合提示词规整"})[0]
        self.status.setText("综合提示词规整中……")
        self._begin_busy("综合提示词规整")

    def _expand_preview(self):
        """对综合提示词做扩写（大模型）。"""
        text = self.preview.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无内容", "请先点击“综合提示词规整”生成内容，或直接粘贴要扩写的提示词。")
            return
        if self._organize_task:
            self.status.setText("已有任务在执行。")
            return
        from app.services.keyword_organize_service import KeywordOrganizeService
        organizer = KeywordOrganizeService(self.service.db_path)
        if not self.task_manager:
            try:
                outcome = organizer.expand_prompt(text, self.model_service)
                self.preview.setPlainText(outcome.get("text") or text)
                self.status.setText("综合提示词已扩写。")
            except Exception as exc:
                self.status.setText(f"扩写暂不可用：{exc}")
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
        self.status.setText("综合提示词扩写中……")
        self._begin_busy("综合提示词扩写")

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
        self.status.setText(f"已保存到知识库「{data['category_name']}」分类下的「{data['title']}」（条目 #{knowledge_id}）。")

    # ---------- 任务回调 ----------

    def _on_progress(self, task_id, value):
        if task_id == self._organize_task:
            label = "综合提示词扩写中" if self._organize_mode == "expand" else "综合提示词规整中"
            self.status.setText(f"{label}……{value:.0f}%")
            self.progress_bar.setValue(int(value))
        elif task_id == self._extract_task:
            self.extract_status.setText(f"正在自动拆分资料中的提示词……{value:.0f}%")
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
                self.preview.setPlainText((outcome or {}).get("text") or self.preview.toPlainText())
                self.status.setText("综合提示词已扩写（可继续编辑后保存）。")
            else:
                self._show_preview(outcome)
        elif task_id == self._extract_task:
            self._extract_task = None
            self._fill_cards(outcome)
        elif task_id == self._expand_task:
            self._expand_task = None
            texts = outcome if isinstance(outcome, list) else []
            target_cards = [c for c in self._cards if c["check"].isChecked() and c["prompt"].toPlainText().strip()][:8]
            for card, text in zip(target_cards, texts):
                if text:
                    card["prompt"].setPlainText(text)
            self.extract_status.setText(f"已扩写 {len(texts)} 条提示词（可继续编辑后保存）。")

    def _on_failed(self, task_id, message):
        if task_id in (self._organize_task, self._extract_task, self._expand_task):
            self._end_busy()
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self._organize_task = self._extract_task = self._expand_task = None
            target = self.extract_status if task_id == self._extract_task else self.status
            target.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        if task_id == self._organize_task:
            self._organize_task = None
            self.status.setText(f"失败：{message}")
        elif task_id == self._extract_task:
            self._extract_task = None
            self.extract_status.setText(f"自动拆分暂不可用：{message}")
        elif task_id == self._expand_task:
            self._expand_task = None
            self.extract_status.setText(f"扩写暂不可用：{message}")

    def closeEvent(self, event):
        if self.task_manager:
            for signal in (self.task_manager.task_progress, self.task_manager.task_finished, self.task_manager.task_failed):
                for slot in (self._on_progress, self._on_finished, self._on_failed):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        super().closeEvent(event)
