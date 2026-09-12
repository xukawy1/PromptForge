# -*- coding: utf-8 -*-
"""Phase 12.2/13 补丁：结果窗体真规整、采集页布局、skill 关键字显示、生成页单框。"""
from pathlib import Path

BASE = Path(__file__).resolve().parent

def patch(path, pairs):
    p = BASE / path
    t = p.read_text(encoding="utf-8")
    ok = 0
    for old, new in pairs:
        if old in t:
            t = t.replace(old, new, 1)
            ok += 1
        else:
            print("MISS in", path, ":", old[:70].replace("\n", " "))
    p.write_text(t, encoding="utf-8")
    print(path, f"{ok}/{len(pairs)}")

# ---------- 1) CollectorResultDialog：真提示词卡规整 ----------
patch("app/ui/pages/collector/dialogs.py", [
 ("""        self.preview_llm_btn = QPushButton("AI 规整（预览，调用大模型）")
        self.preview_llm_btn.clicked.connect(lambda: self._organize_preview(use_llm=True))
        self.preview_kw_btn = QPushButton("关键词规整（预览）")
        self.preview_kw_btn.clicked.connect(lambda: self._organize_preview(use_llm=False))
        self.re_run_btn = QPushButton("重新规整")
        self.re_run_btn.clicked.connect(lambda: self._organize_preview(self._last_use_llm if hasattr(self, "_last_use_llm") else False))""",
  """        self.preview_llm_btn = QPushButton("规整为图片/视频提示词（AI）")
        self.preview_llm_btn.clicked.connect(lambda: self._organize_preview(use_llm=True))
        self.preview_kw_btn = QPushButton("基础骨架规整")
        self.preview_kw_btn.clicked.connect(lambda: self._organize_preview(use_llm=False))
        self.re_run_btn = QPushButton("重新规整")
        self.re_run_btn.clicked.connect(lambda: self._organize_preview(getattr(self, "_last_use_llm", True)))"""),

 ("""    def _organize_preview(self, use_llm):
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
                outcome = organizer.organize_source(self.source_id, use_llm=use_llm, model_service=self.model_service)
                self._show_preview(outcome)
            except Exception as exc:
                self.status.setText(f"规整失败：{exc}")
            return
        model_service = self.model_service
        def worker(ctx):
            ctx.report_progress(30)
            outcome = organizer.organize_source(self.source_id, use_llm=use_llm, model_service=model_service)
            ctx.report_progress(95)
            return outcome
        self._organize_task = self.task_manager.submit(
            fn=worker, task_type="collector.organize", input_data={"label": "规整预览"})[0]
        self.status.setText("规整中……")""",
  """    def _organize_preview(self, use_llm):
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
        self.status.setText("规整中……")"""),

 ("""    def _show_preview(self, outcome):
        keywords = outcome.get("keywords") or []
        categories = outcome.get("categories") or []
        if outcome.get("status") == "duplicate":
            self.status.setText("该来源此前已规整入库；可在预览中修改后直接保存为新条目。")
        row = self.service.sources.get(self.source_id) if self.service else None
        doc_rows = []
        if row:
            from app.database.repositories.core import DocumentRepository
            doc_rows = DocumentRepository(self.service.db_path).list(1, 0, "source_id=?", (self.source_id,))
        content = (doc_rows[0].get("content") if doc_rows else "") or ""
        preview_text = (
            f"【标题】{row.get('title') if row else ''}\\n"
            f"【自动分类】{' / '.join(categories) if categories else '未匹配'}\\n"
            f"【关键词索引】{', '.join(keywords) or '无'}\\n\\n"
            f"{content[:1500]}"
        )
        self.preview.setPlainText(preview_text)
        self.status.setText("规整完成，已在下方预览；可编辑后点“保存到知识库…”。")""",
  """    def _show_preview(self, outcome):
        self.preview.setPlainText(outcome.get("text") or "")
        mode = outcome.get("mode")
        if mode == "llm":
            self.status.setText(f"已规整为图片/视频提示词卡（模型：{outcome.get('model')}）；可编辑后点“保存到知识库…”。")
        else:
            self.status.setText("已生成基础提示词骨架；连接默认 LLM 后可重新规整为完整提示词。")"""),
])

# ---------- 2) CollectorPage：移除内容预览区，操作行上移 ----------
patch("app/ui/pages/collector/page.py", [
 ("""        layout.addWidget(title)
        layout.addWidget(QLabel(
            "左侧选择采集方式并提交任务；采集完成后可一键“规整到知识库”——自动提取关键词、匹配分类、"
            "生成提示词要素卡片（可选大模型总结），并在知识库中按关键词索引调用。"
        ))

        splitter = QSplitter()""",
  """        layout.addWidget(title)
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
        layout.addWidget(QLabel(
            "左侧选择采集方式并提交任务；完成后在对应页“识别图片文字并归纳”，或点上方“查看采集结果”"
            "把内容规整为可直接使用的图片/视频提示词并保存到知识库。"
        ))

        splitter = QSplitter()"""),

 ("""        result_row_widget = QWidget()
        result_row = QHBoxLayout(result_row_widget)
        self.auto_organize = QCheckBox("采集完成后自动规整到知识库")
        self.auto_organize.setChecked(bool(self.config.get("auto_organize", False)) if hasattr(self.config, "get") else False)
        self.auto_organize.toggled.connect(self._auto_organize_changed)
        self.view_result_btn = QPushButton("查看采集结果（AI 规整 / 预览 / 保存）")
        self.view_result_btn.setObjectName("primary")
        self.view_result_btn.setEnabled(False)
        self.view_result_btn.clicked.connect(self.open_result_dialog)
        result_row.addWidget(self.auto_organize)
        result_row.addStretch(1)
        result_row.addWidget(self.view_result_btn)
        layout.addWidget(result_row_widget)

        # ---- 预览区 ----
        preview_group = QGroupBox("内容预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_title = QLabel("本次采集内容 / 历史详情")
        self.preview_title.setObjectName("sectionTitle")
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("采集完成后这里显示正文内容预览；点击左侧历史条目可回看该次采集的完整内容。\\n"
                                        "点击上方“查看采集结果”可打开结果窗体：AI 规整预览、编辑并保存到知识库。")
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_group, 1)""",
  """        # 归纳结果区域由各采集页的大文本框承担（见 _build_url_page / _build_file_page）""",),

 # _preview_current / preview 引用清理
 ("""    def _preview_current(self, result):
        source_id = result.get("source_id")
        if source_id is None or not self.service:
            return
        try:
            data = self.service.load_source_content(source_id)
        except Exception:
            return
        if data and data.get("content"):
            self.preview_title.setText(f"标题：{data.get('title') or ''}    类型：{data.get('kind')}")
            self.preview.setPlainText(data["content"][:20000])""",
  """    def _preview_current(self, result):
        # 预览已由各采集页的归纳结果框承担；保留空实现避免旧调用报错。
        return"""),
])

# ---------- 3) SkillPage：关键字显示区 ----------
patch("app/ui/pages/skill/page.py", [
 ("""        self.skill_combo = QComboBox()
        self.skill_combo.currentIndexChanged.connect(self.show)
        left_layout.addWidget(self.skill_combo)
        self.detail = QPlainTextEdit()""",
  """        self.skill_combo = QComboBox()
        self.skill_combo.currentIndexChanged.connect(self.show)
        left_layout.addWidget(self.skill_combo)
        self.keywords_label = QLabel("已安装关键字：加载中…")
        self.keywords_label.setObjectName("panelHint")
        self.keywords_label.setWordWrap(True)
        left_layout.addWidget(self.keywords_label)
        self.detail = QPlainTextEdit()"""),

 ("""    def refresh(self):
        self.skills = self.skill_service.list_skills() if self.skill_service else []
        self.skill_combo.blockSignals(True)
        self.skill_combo.clear()
        for s in self.skills:
            self.skill_combo.addItem(f"{s.get('keyword')}（{s.get('file_count') or 1} 文件）", s["id"])
        self.skill_combo.blockSignals(False)
        if self.skills:
            self.show(0)""",
  """    def refresh(self):
        self.skills = self.skill_service.list_skills() if self.skill_service else []
        self.skill_combo.blockSignals(True)
        self.skill_combo.clear()
        for s in self.skills:
            self.skill_combo.addItem(f"{s.get('keyword')}（{s.get('file_count') or 1} 文件）", s["id"])
        self.skill_combo.blockSignals(False)
        keywords = "、".join(s.get("keyword") or "" for s in self.skills) or "暂无（请点击下方“安装”按钮导入 skill 文件/文件夹）"
        self.keywords_label.setText(f"已安装 {len(self.skills)} 个，关键字：{keywords}")
        if self.skills:
            self.show(0)"""),
])

# ---------- 4) GeneratorPage：单框“扩写提示词” ----------
patch("app/ui/pages/generator/page.py", [
 ("""        self.tabs = QTabWidget()
        self.en_result = QTextEdit()
        self.en_result.setReadOnly(True)
        self.zh_result = QTextEdit()
        self.zh_result.setReadOnly(True)
        self.tabs.addTab(self.en_result, "English 提示词")
        self.tabs.addTab(self.zh_result, "中文翻译")
        right.addWidget(self.tabs, 1)""",
  """        result_label = QLabel("扩写提示词")
        result_label.setObjectName("sectionTitle")
        right.addWidget(result_label)
        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        right.addWidget(self.result_box, 1)"""),

 ("""        self.result_tabs = QTabWidget()""",
  """        self.result_tabs = QTabWidget()  # 兼容保留"""),

 ("""    def _on_stream_text(self, text):
        self._stream_buffer = text
        parsed = self.generation_service.parse_result(text) if self.generation_service else {"en": text, "zh": ""}
        self.en_result.setPlainText(parsed.get("en") or "")
        self.zh_result.setPlainText(parsed.get("zh") or "")
        self.progress_info.setText(f"已生成 {len(text)} 字符……")""",
  """    def _on_stream_text(self, text):
        self._stream_buffer = text
        self.result_box.setPlainText(text)
        self.progress_info.setText(f"已生成 {len(text)} 字符……")"""),

 ("""    def _handle_result(self, outcome):
        self.current_result = outcome.get("result") or ""
        parsed = self.generation_service.parse_result(self.current_result)
        self.en_result.setPlainText(parsed.get("en") or "")
        self.zh_result.setPlainText(parsed.get("zh") or "")
        negative = parsed.get("negative") or ""
        self.parsed.setText(
            f"英文 {len(parsed.get('en') or '')} 字 · 中文 {len(parsed.get('zh') or '')} 字 · 负向 {len(negative)} 字 · 参数 {'有' if parsed.get('params') else '无'}"
        )""",
  """    def _handle_result(self, outcome):
        self.current_result = outcome.get("result") or ""
        parsed = self.generation_service.parse_result(self.current_result)
        self.result_box.setPlainText(self.current_result)
        negative = parsed.get("negative") or ""
        self.parsed.setText(
            f"英文 {len(parsed.get('en') or '')} 字 · 中文 {len(parsed.get('zh') or '')} 字 · 负向 {len(negative)} 字 · 参数 {'有' if parsed.get('params') else '无'}"
        )"""),

 ("""        self._stream_buffer = ""
        self.en_result.setPlainText("")
        self.zh_result.setPlainText("")
        self.progress_bar.setRange(0, 0)""",
  """        self._stream_buffer = ""
        self.result_box.setPlainText("")
        self.progress_bar.setRange(0, 0)""",)
])
print("ALL_PATCHES_DONE")
