from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QTextEdit, QMessageBox, QSplitter, QComboBox, QProgressBar, QFileDialog,
    QDialog, QFormLayout, QDialogButtonBox, QPlainTextEdit, QLineEdit,
    QTabWidget,
)


class SaveKnowledgeDialog(QDialog):
    def __init__(self, knowledge_service, default_title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("保存到知识库")
        form = QFormLayout(self)
        self.title = QLineEdit(default_title)
        self.category = QComboBox()
        self.category.addItem("未分类", None)
        if knowledge_service:
            for c in knowledge_service.categories.list(1000, order_by="sort_order ASC,id ASC"):
                self.category.addItem(c["name"], c["id"])
        self.category.setToolTip("没有合适的分类？请先到“知识库”页面新增分类。")
        form.addRow("名称", self.title)
        form.addRow("分类", self.category)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self):
        return {"title": self.title.text().strip(), "category_id": self.category.currentData()}


class SkillPage(QWidget):
    """Skill 工坊：安装本地 skill，按关键字调用格式，把知识库素材详细扩充为符合 skill 规范的成品提示词。"""

    def __init__(self, skill_service=None, knowledge_service=None, model_service=None, task_manager=None, config=None, generation_service=None):
        super().__init__()
        self.skill_service = skill_service
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.task_manager = task_manager
        self.config = config or {}
        self.generation_service = generation_service
        self.skills = []
        self.materials = []
        self._material_by_id = {}
        self._active_tasks = {}
        self.current_result = ""

        layout = QVBoxLayout(self)
        title = QLabel("Skill 工坊")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "把各大网站下载的 skill 文件（.md/.txt）或文件夹一键安装进来，软件读取其中的书写格式；"
            "选择 skill 与知识库提示词素材后，调用本地大模型把素材详细扩充成符合该 skill 规范的成品提示词，可再一键翻译。"
        ))

        splitter = QSplitter()
        left = QWidget(); left_layout = QVBoxLayout(left)
        caption = QLabel("已安装 Skill")
        caption.setObjectName("sectionTitle")
        left_layout.addWidget(caption)
        self.skill_combo = QComboBox()
        self.skill_combo.currentIndexChanged.connect(self.show)
        left_layout.addWidget(self.skill_combo)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        left_layout.addWidget(self.detail, 1)
        btn_row = QHBoxLayout()
        install_file_btn = QPushButton("安装 Skill 文件…")
        install_file_btn.clicked.connect(self.install_file)
        install_dir_btn = QPushButton("安装 Skill 文件夹…")
        install_dir_btn.clicked.connect(self.install_dir)
        rename_btn = QPushButton("重命名")
        rename_btn.setToolTip("修改已安装 Skill 在下拉列表中的名称")
        rename_btn.clicked.connect(self.rename_skill)
        delete_btn = QPushButton("删除")
        delete_btn.clicked.connect(self.delete_skill)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        for b in (install_file_btn, install_dir_btn, rename_btn, delete_btn, refresh_btn):
            btn_row.addWidget(b)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        right = QWidget(); right_layout = QVBoxLayout(right)
        material_label = QLabel("提示词素材（先选知识分类，再选该分类下的条目）")
        material_label.setObjectName("sectionTitle")
        material_row = QHBoxLayout()
        material_row.addWidget(material_label)
        material_row.addStretch()
        material_refresh_btn = QPushButton("刷新素材")
        material_refresh_btn.setToolTip("重新从知识库加载素材列表（内容较多时请稍候）")
        material_refresh_btn.clicked.connect(self.refresh_materials)
        material_row.addWidget(material_refresh_btn)
        right_layout.addLayout(material_row)
        material_split = QSplitter()
        self.category_list = QListWidget()
        self.category_list.currentRowChanged.connect(self._on_category_selected)
        material_split.addWidget(self.category_list)
        self.material_list = QListWidget()
        self.material_list.currentRowChanged.connect(self._preview_material)
        material_split.addWidget(self.material_list)
        material_split.setSizes([200, 420])
        right_layout.addWidget(material_split, 1)
        self.material_preview = QTextEdit()
        self.material_preview.setReadOnly(True)
        self.material_preview.setMaximumHeight(84)
        right_layout.addWidget(self.material_preview)

        manual_label = QLabel("或手动输入素材（填写后优先生效，可直接交给 Skill 扩写）")
        manual_label.setObjectName("sectionTitle")
        right_layout.addWidget(manual_label)
        self.manual_material = QTextEdit()
        self.manual_material.setPlaceholderText(
            "在这里手动输入提示词素材/草稿（例如：银发少女，雨夜霓虹街头……）\n"
            "填写后点击「按 Skill 规范生成」，会结合上方选择的 Skill 格式进行详细扩写。")
        self.manual_material.setMinimumHeight(96)
        self.manual_material.setMaximumHeight(150)
        right_layout.addWidget(self.manual_material)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("按 Skill 规范生成（详细扩充）")
        self.run_btn.clicked.connect(self.run_skill)
        lang_label = QLabel("翻译为：")
        self.lang_combo = QComboBox()
        if self.generation_service:
            for lang in self.generation_service.TRANSLATION_LANGUAGES:
                self.lang_combo.addItem(lang)
        translate_btn = QPushButton("一键翻译结果")
        translate_btn.clicked.connect(self.translate_result)
        run_row.addWidget(self.run_btn)
        run_row.addWidget(lang_label)
        run_row.addWidget(self.lang_combo)
        run_row.addWidget(translate_btn)
        run_row.addStretch()
        right_layout.addLayout(run_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        right_layout.addWidget(self.progress)
        self.status = QLabel("就绪")
        self.status.setObjectName("panelHint")
        self.status.setWordWrap(True)
        right_layout.addWidget(self.status)

        self.result_tabs = QTabWidget()
        self.result_original = QTextEdit()
        self.result_original.setReadOnly(True)
        self.result_translated = QTextEdit()
        self.result_translated.setReadOnly(True)
        self.result_tabs.addTab(self.result_original, "生成结果")
        self.result_tabs.addTab(self.result_translated, "翻译译文")
        right_layout.addWidget(self.result_tabs, 2)

        save_row = QHBoxLayout()
        self.save_prompt_btn = QPushButton("保存为 Prompt")
        self.save_prompt_btn.clicked.connect(self.save_prompt)
        self.save_knowledge_btn = QPushButton("保存到知识库…")
        self.save_knowledge_btn.clicked.connect(self.save_knowledge)
        save_row.addWidget(self.save_prompt_btn)
        save_row.addWidget(self.save_knowledge_btn)
        save_row.addStretch()
        right_layout.addLayout(save_row)
        splitter.addWidget(right)
        splitter.setSizes([340, 660])
        layout.addWidget(splitter, 1)
        self._materials_loaded = False
        self._category_map = {}
        self.refresh()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)

    # ---------- 安装与管理 ----------

    def install_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 skill 文件", "", "Skill 文件 (*.md *.markdown *.txt)")
        if path:
            self._install(path)

    def install_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择 skill 文件夹")
        if path:
            self._install(path)

    def _install(self, path):
        if not self.skill_service:
            self.status.setText("Skill 服务尚未初始化。")
            return
        try:
            outcome = self.skill_service.install_from_path(path)
        except Exception as exc:
            QMessageBox.warning(self, "安装失败", str(exc))
            return
        self.status.setText(f"安装成功：关键字「{outcome['keyword']}」（{outcome['file_count']} 个文件，{'更新' if outcome['status'] == 'updated' else '新建'}）。")
        self.refresh()

    # 内置 skill 的简短功能说明（下拉菜单显示用；未收录的 skill 自动取描述前段）
    SKILL_SHORT = {
        "h3-prompt-writing": "MiniMax H3 视频提示词",
        "h3-seg-prompt-design": "H3 长视频分段设计",
        "start-h3-prompts-from-scratch": "H3 提示词从零上手",
        "midjourney-prompt-engineering": "Midjourney 提示词工程",
        "prompt-engine": "通用提示词引擎",
        "prompt-build": "提示词搭建法",
        "prompt-enhance": "提示词增强扩写",
        "prompt-library": "提示词库合集",
        "prompt-adapt": "跨模型适配改写",
        "image-to-prompt": "图生提示词",
        "gpt-image2-skill": "GPT 图像提示词",
        "gpt-image-2-style-library": "GPT-Image 风格库/模板",
        "ai-visual-story-prompt-library": "视觉故事提示词库",
        "3d-animation-short-generator": "3D 动画短片",
        "brand-promo-video-generator": "品牌宣传片脚本",
        "co-op-game-intro-generator": "双人游戏开场",
        "handdrawn-live-video-generator": "手绘实拍视频",
        "minimalist-product-ad-generator": "极简产品广告",
        "mv-subtitle-skill-confirmed": "MV 歌词字幕设计",
        "paper-collage-explainer-generator": "纸艺拼贴解说",
        "papercraft-stop-motion-explainer": "定格纸艺解说",
        "awesome-chatgpt-prompts": "ChatGPT 提示词合集",
        "awesome-chatgpt-prompts-csv": "ChatGPT 提示词表",
    }

    def _short_label(self, skill):
        keyword = skill.get("keyword") or ""
        short = self.SKILL_SHORT.get(keyword)
        if not short:
            desc = (skill.get("description") or "").strip().splitlines()
            short = (desc[0][:16] if desc and desc[0] else "")
            short = short.strip("# -·")
        return f"{keyword} · {short}" if short else keyword

    def refresh(self):
        self.skills = self.skill_service.list_skills() if self.skill_service else []
        self.skill_combo.blockSignals(True)
        self.skill_combo.clear()
        if not self.skills:
            self.skill_combo.addItem("暂无 Skill（点下方“安装”导入文件/文件夹）", None)
        for s in self.skills:
            self.skill_combo.addItem(self._short_label(s), s["id"])
        self.skill_combo.blockSignals(False)
        if self.skills:
            self.show(0)
        else:
            self.detail.setPlainText("尚未安装任何 Skill。点击下方“安装 Skill 文件…/文件夹…”即可导入。")

    def _current_skill(self):
        data = self.skill_combo.currentData()
        for s in self.skills:
            if s["id"] == data:
                return s
        return None

    def show(self, index):
        s = self._current_skill()
        if s:
            self.detail.setPlainText((s.get("description") or "") + "\n\n" + (s.get("content") or ""))

    def rename_skill(self):
        s = self._current_skill()
        if not s or not self.skill_service:
            self.status.setText("请先选择要重命名的 Skill。")
            return
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "重命名 Skill", "新的名称（下拉列表显示用）：",
            QLineEdit.EchoMode.Normal, s.get("keyword") or "")
        if not ok:
            return
        try:
            self.skill_service.rename_skill(s["id"], new_name)
        except Exception as exc:
            QMessageBox.warning(self, "重命名失败", str(exc))
            return
        self.status.setText(f"已将 Skill 重命名为「{new_name.strip()}」。")
        self.refresh()

    def delete_skill(self):
        s = self._current_skill()
        if not s or not self.skill_service:
            return
        if QMessageBox.question(self, "确认", f"确定删除 Skill「{s.get('keyword')}」？") == QMessageBox.Yes:
            self.skill_service.delete(s["id"])
            self.refresh()

    # ---------- 素材（分类 → 条目 两级） ----------

    def showEvent(self, event):
        super().showEvent(event)
        if not self._materials_loaded:
            self.refresh_materials()

    def refresh_materials(self):
        """轻量加载素材索引（不含正文），进入页面秒开；正文在选择时按需读取。"""
        if not self.skill_service:
            return
        self.materials = self.skill_service.list_material_index(400)
        self._material_by_id = {k["id"]: k for k in self.materials}
        self._category_map = self.skill_service.category_name_map()
        self.category_list.blockSignals(True)
        self.category_list.clear()
        names = ["全部", "未分类"]
        seen = set()
        for k in self.materials:
            name = self._category_name(k)
            if name not in seen:
                seen.add(name)
                names.append(name)
        for n in names:
            self.category_list.addItem(n)
        self.category_list.blockSignals(False)
        if self.category_list.count():
            self.category_list.setCurrentRow(0)
        self._fill_materials()
        self._materials_loaded = True

    def _category_name(self, item):
        cid = item.get("category_id")
        if cid is None:
            return "未分类"
        return self._category_map.get(cid) or "未分类"

    def _on_category_selected(self, index):
        self._fill_materials()

    def _fill_materials(self):
        category = self.category_list.currentItem()
        cat_name = category.text() if category else "全部"
        self.material_list.blockSignals(True)
        self.material_list.clear()
        for k in self.materials:
            name = self._category_name(k)
            if cat_name in ("全部",) or name == cat_name:
                created = (k.get("created_at") or "")[:19]
                item_text = f"{created}  {k.get('title') or '(未命名)'}"
                from PySide6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, k["id"])
                self.material_list.addItem(item)
        self.material_list.blockSignals(False)

    def _preview_material(self, index):
        k = self._selected_material_row()
        if not k:
            self.material_preview.setPlainText("")
            return
        try:
            content = self.skill_service.get_material_content(k["id"]) if self.skill_service else ""
        except Exception:
            content = ""
        self.material_preview.setPlainText(content[:800])

    def _selected_material_row(self):
        item = self.material_list.currentItem()
        if not item:
            return None
        return self._material_by_id.get(item.data(Qt.UserRole))

    def _selected_material(self):
        """素材来源：手动输入优先；否则取列表中选中的知识条目正文。"""
        manual = self.manual_material.toPlainText().strip()
        if manual:
            return manual
        k = self._selected_material_row()
        if not k or not self.skill_service:
            return ""
        try:
            return self.skill_service.get_material_content(k["id"])
        except Exception:
            return ""

    # ---------- 生成 ----------

    def run_skill(self):
        s = self._current_skill()
        if not s or not self.skill_service:
            self.status.setText("请先在上方下拉框选择一个 Skill。")
            return
        material = self._selected_material()
        if not material:
            self.status.setText("请先选择提示词素材，或在下方的「手动输入素材」框里填写内容后再生成。")
            return
        skill_id = s["id"]
        self.run_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText("正在识别 skill 规范并把素材详细扩充为成品提示词……大模型生成需要一些时间。")
        self.result_original.setPlainText("")
        self.result_translated.setPlainText("")
        if not self.task_manager:
            try:
                outcome = self.skill_service.apply_skill(skill_id, material, self.model_service)
                self._handle_result(outcome)
            except Exception as exc:
                self._show_error(str(exc))
            finally:
                self.run_btn.setEnabled(True)
                self.progress.setVisible(False)
            return
        if self._active_tasks:
            self.status.setText("已有 Skill 生成任务在执行。")
            self.run_btn.setEnabled(True)
            self.progress.setVisible(False)
            return

        def worker(ctx):
            ctx.report_progress(30)
            outcome = self.skill_service.apply_skill(skill_id, material, self.model_service,
                                                     on_progress=lambda v: ctx.report_progress(float(v)))
            ctx.report_progress(95)
            return outcome

        task_id, future, ctx = self.task_manager.submit(
            fn=worker, task_type="skill.apply", input_data={"label": "skill生成"}
        )
        self._active_tasks[task_id] = skill_id

    def translate_result(self):
        text = self.result_original.toPlainText()
        if not text.strip():
            self.status.setText("还没有可翻译的生成结果。")
            return
        if not self.generation_service:
            self.status.setText("翻译服务尚未初始化。")
            return
        target = self.lang_combo.currentText() if self.lang_combo.count() else "中文（简体）"
        self.status.setText(f"正在翻译为 {target}……")
        if not self.task_manager:
            try:
                translated = self.generation_service.translate(text, target)
                self.result_translated.setPlainText(translated)
                self.status.setText(f"翻译完成（{target}）。")
            except Exception as exc:
                self.status.setText(f"翻译失败：{exc}")
            return
        if self._active_tasks:
            self.status.setText("已有任务在执行，请稍候。")
            return
        generation_service = self.generation_service
        task_id, future, ctx = self.task_manager.submit(
            fn=lambda c: generation_service.translate(text, target),
            task_type="skill.translate", input_data={"label": "翻译"},
        )
        self._active_tasks[task_id] = "translate"

    def _on_task_progress(self, task_id, value):
        if task_id in self._active_tasks and self._active_tasks[task_id] != "translate":
            self.progress.setRange(0, 100)
            self.progress.setValue(int(value))

    def _on_task_finished(self, task_id, outcome):
        if task_id not in self._active_tasks:
            return
        kind = self._active_tasks.pop(task_id)
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        if kind == "translate":
            self.result_translated.setPlainText(str(outcome))
            self.result_tabs.setCurrentWidget(self.result_translated)
            self.status.setText("翻译完成。")
        else:
            self._handle_result(outcome)

    def _on_task_failed(self, task_id, message):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id)
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.status.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        self._show_error(message)

    def _handle_result(self, outcome):
        self.current_result = (outcome.get("text") or "").strip()
        self.result_original.setPlainText(self.current_result)
        self.result_tabs.setCurrentWidget(self.result_original)
        if not self.current_result:
            self.status.setText("生成结果为空：请检查是否已选择素材与默认模型，或更换模型后重试。")
            return
        mode = outcome.get("mode")
        if mode == "rule":
            self.status.setText("未连接大模型，已按规则拼接 skill 格式与素材；可在模型中心设置默认 LLM 后重新生成。")
        elif mode == "rule_fallback":
            self.status.setText("模型未返回内容（skill 文档较长可能超出上下文），已自动用规则拼接兜底——"
                                "建议更换更大的模型或在模型中心调大上下文后重新生成。")
        else:
            self.status.setText(f"已按 skill 规范详细扩充完成（模型：{outcome.get('model')}），可翻译、保存。")

    def _show_error(self, message):
        self.status.setText(f"失败：{message}")

    # ---------- 保存 ----------

    def save_prompt(self):
        if not self.current_result or not self.skill_service:
            self.status.setText("还没有可保存的生成结果。")
            return
        try:
            outcome = self.skill_service.save_result_as_prompt(self.current_result)
        except Exception as exc:
            self.status.setText(f"保存失败：{exc}")
            return
        self.status.setText(outcome.get("message", "已保存"))

    def save_knowledge(self):
        if not self.current_result or not self.skill_service:
            self.status.setText("还没有可保存的生成结果。")
            return
        s = self._current_skill()
        if not s:
            self.status.setText("请先选择 Skill。")
            return
        dialog = SaveKnowledgeDialog(self.knowledge_service, default_title=f"Skill 成品：{s.get('keyword')}", parent=self)
        if dialog.exec():
            data = dialog.data()
            try:
                knowledge_id = self.skill_service.save_result_to_knowledge(
                    self.current_result, s["id"], title=data["title"], category_id=data["category_id"])
            except Exception as exc:
                self.status.setText(f"保存失败：{exc}")
                return
            self.status.setText(f"已保存到知识库（条目 #{knowledge_id}），可在知识库对应分类中查看。")
