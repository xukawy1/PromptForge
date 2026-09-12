import json
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLineEdit, QPushButton,
    QLabel, QTextEdit, QDialog, QFormLayout, QDialogButtonBox,
    QMessageBox, QCheckBox, QComboBox,
)


class PromptEditDialog(QDialog):
    def __init__(self, service, item=None, knowledge_service=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.knowledge_service = knowledge_service
        self.item = item or {}
        self.setWindowTitle("编辑 Prompt" if item else "新增 Prompt")
        self.resize(720, 680)
        form = QFormLayout(self)
        self.title = QLineEdit(self.item.get("title", ""))
        self.text = QTextEdit(self.item.get("prompt_text", ""))
        self.neg = QTextEdit(self.item.get("negative_prompt", ""))
        self.typ = QLineEdit(self.item.get("prompt_type", "image"))
        self.model = QLineEdit(self.item.get("target_model", ""))
        self.language = QLineEdit(self.item.get("language", "en"))
        for label, widget in (("标题", self.title), ("正向 Prompt", self.text), ("Negative Prompt", self.neg),
                              ("类型", self.typ), ("目标模型", self.model), ("语言", self.language)):
            form.addRow(label, widget)

        sync_label = QLabel("同步到知识库（保存后可在知识库中按分类调用）")
        sync_label.setObjectName("sectionTitle")
        form.addRow(sync_label)
        sync_row = QHBoxLayout()
        self.sync_knowledge = QCheckBox("同时保存为知识条目")
        self.category = QComboBox()
        self.category.addItem("不同步分类", None)
        category_names = []
        if knowledge_service:
            for c in knowledge_service.categories.list(1000, order_by="sort_order ASC,id ASC"):
                self.category.addItem(c["name"], c["id"])
                category_names.append(c["name"])
        self.category.setToolTip("没有合适的分类？请先到“知识库”页面新增分类，再回到这里刷新选择。")
        sync_row.addWidget(self.sync_knowledge, 1)
        sync_row.addWidget(QLabel("分类："))
        sync_row.addWidget(self.category, 2)
        form.addRow("", sync_row)
        self.knowledge_title = QLineEdit()
        self.knowledge_title.setPlaceholderText("知识条目名称；留空使用 Prompt 标题")
        form.addRow("知识名称", self.knowledge_title)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self):
        return {
            "title": self.title.text().strip(),
            "prompt_text": self.text.toPlainText().strip(),
            "negative_prompt": self.neg.toPlainText().strip() or None,
            "prompt_type": self.typ.text().strip() or "image",
            "target_model": self.model.text().strip() or None,
            "language": self.language.text().strip() or "en",
            "sync_knowledge": self.sync_knowledge.isChecked(),
            "knowledge_category_id": self.category.currentData(),
            "knowledge_title": self.knowledge_title.text().strip(),
        }


class PromptLibraryPage(QWidget):
    """Prompt 库：查看、搜索、管理已保存的全部 Prompt，并可同步到知识库。"""

    def __init__(self, service=None, knowledge_service=None):
        super().__init__()
        self.service = service
        self.knowledge_service = knowledge_service
        self.items = []
        self.page = 1
        self.page_size = 50

        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        hint = QLabel(
            "页面说明：这里是你保存的全部 Prompt（来自生成结果、图片反推或手工录入）。\n"
            "用法：搜索或翻页浏览 → 点击条目查看详情与来源追溯 → 新增/编辑时可勾选“同步到知识库”并选择分类；"
            "已有条目可点右侧“同步到知识库”。页面切换与点刷新均会重新加载。"
        )
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题 / 正文 / 负向 / 目标模型…")
        self.search.returnPressed.connect(self.refresh)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.refresh)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(search_btn)
        bar.addWidget(refresh_btn)
        left.addLayout(bar)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show)
        left.addWidget(self.list)
        page_bar = QHBoxLayout()
        prev_btn = QPushButton("上一页")
        prev_btn.clicked.connect(self.prev_page)
        next_btn = QPushButton("下一页")
        next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel("第 1 页")
        page_bar.addWidget(prev_btn)
        page_bar.addWidget(self.page_label)
        page_bar.addWidget(next_btn)
        page_bar.addStretch()
        left.addLayout(page_bar)
        buttons = QHBoxLayout()
        for label, slot in (("新增", self.add), ("编辑", self.edit), ("删除", self.delete)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch()
        left.addLayout(buttons)
        layout.addLayout(left, 2)

        right = QVBoxLayout()
        self.detail_title = QLabel("Prompt 详情")
        self.detail_title.setObjectName("sectionTitle")
        self.trace = QLabel("来源：无")
        self.trace.setObjectName("panelHint")
        self.trace.setWordWrap(True)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right.addWidget(self.detail_title)
        right.addWidget(self.trace)
        right.addWidget(self.detail)
        sync_row = QHBoxLayout()
        self.sync_btn = QPushButton("同步到知识库…")
        self.sync_btn.clicked.connect(self.sync_to_knowledge)
        sync_row.addStretch()
        sync_row.addWidget(self.sync_btn)
        right.addLayout(sync_row)
        layout.addLayout(right, 3)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        if not self.service:
            return
        result = self.service.search_prompts(self.search.text(), self.page, self.page_size)
        self.items = result.get("items", [])
        total = result.get("total", 0)
        max_page = max(1, (total + self.page_size - 1) // self.page_size)
        self.page = min(self.page, max_page)
        self.page_label.setText(f"第 {self.page} / {max_page} 页 · 共 {total} 条")
        self.list.clear()
        for x in self.items:
            created = (x.get("created_at") or "")[:19]
            self.list.addItem(f"{created}  {x.get('title') or '(未命名)'}")

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.refresh()

    def next_page(self):
        self.page += 1
        self.refresh()

    def show(self, row):
        if not 0 <= row < len(self.items):
            return
        x = self.items[row]
        self.detail_title.setText(x.get("title") or "Prompt 详情")
        analysis = x.get("analysis_result") or ""
        translation = ""
        params = analysis
        try:
            parsed = json.loads(analysis)
            if isinstance(parsed, dict):
                translation = parsed.get("translation_zh") or ""
                params = parsed.get("params") or ""
        except (TypeError, ValueError):
            pass
        sections = [x.get("prompt_text") or ""]
        if x.get("negative_prompt"):
            sections.append("\n—— Negative Prompt ——\n" + x["negative_prompt"])
        if translation:
            sections.append("\n—— 中文翻译 ——\n" + translation)
        if params:
            sections.append("\n—— 参数 / 备注 ——\n" + params)
        sections.append(f"\n—— 元信息 ——\n类型：{x.get('prompt_type') or ''}    语言：{x.get('language') or ''}    目标模型：{x.get('target_model') or ''}    创建：{(x.get('created_at') or '')[:19]}")
        self.detail.setPlainText("\n".join(sections))
        try:
            trace = self.service.prompt_source_trace(x["id"])
        except Exception:
            trace = None
        if trace:
            source = trace.get("source")
            image = trace.get("image")
            parts = []
            if source:
                parts.append("来源：" + (source.get("title") or source.get("url") or f"来源#{source['id']}"))
            if image:
                parts.append("图片：" + (image.get("file_path") or f"图片#{image['id']}"))
            self.trace.setText("    ".join(parts) if parts else "来源：无")

    def _sync_prompt_to_knowledge(self, prompt_id, data):
        if not self.knowledge_service:
            return {"message": "知识库服务尚未初始化"}
        category_id = data.get("knowledge_category_id")
        title = data.get("knowledge_title") or data.get("title") or "未命名 Prompt"
        content = data.get("prompt_text") or ""
        if data.get("negative_prompt"):
            content += "\n\nNegative prompt: " + data["negative_prompt"]
        knowledge_id = self.knowledge_service.create_knowledge({
            "source_type": "prompt", "source_id": prompt_id,
            "title": title[:120], "content": content,
            "summary": "同步自 Prompt 库",
            "category_id": category_id, "knowledge_type": "prompt", "confidence": 1.0,
        })
        return {"knowledge_id": knowledge_id, "message": "已同步到知识库"}

    def add(self):
        if not self.service:
            return
        dialog = PromptEditDialog(self.service, knowledge_service=self.knowledge_service, parent=self)
        if dialog.exec() and dialog.data()["prompt_text"]:
            data = dialog.data()
            prompt_id = self.service.create_prompt({k: v for k, v in data.items() if not k.startswith(("sync", "knowledge"))})
            if data.get("sync_knowledge"):
                outcome = self._sync_prompt_to_knowledge(prompt_id, data)
                QMessageBox.information(self, "已保存", "Prompt 已保存，" + outcome.get("message", ""))
            self.refresh()

    def edit(self):
        row = self.list.currentRow()
        if row < 0 or not self.service:
            return
        dialog = PromptEditDialog(self.service, self.items[row], knowledge_service=self.knowledge_service, parent=self)
        if dialog.exec():
            data = dialog.data()
            if data["prompt_text"]:
                prompt_id = self.items[row]["id"]
                self.service.update_prompt(prompt_id, {k: v for k, v in data.items() if not k.startswith(("sync", "knowledge"))})
                if data.get("sync_knowledge"):
                    outcome = self._sync_prompt_to_knowledge(prompt_id, data)
                    QMessageBox.information(self, "已更新", "Prompt 已更新，" + outcome.get("message", ""))
                self.refresh()
                self.show(row)

    def sync_to_knowledge(self):
        row = self.list.currentRow()
        if row < 0 or not self.service:
            QMessageBox.information(self, "提示", "请先选择一条 Prompt。")
            return
        dialog = PromptEditDialog(self.service, self.items[row], knowledge_service=self.knowledge_service, parent=self)
        dialog.setWindowTitle("同步到知识库")
        dialog.sync_knowledge.setChecked(True)
        dialog.sync_knowledge.setEnabled(False)
        dialog.title.setEnabled(False)
        dialog.text.setEnabled(False)
        dialog.neg.setEnabled(False)
        dialog.typ.setEnabled(False)
        dialog.model.setEnabled(False)
        dialog.language.setEnabled(False)
        if dialog.exec():
            data = dialog.data()
            outcome = self._sync_prompt_to_knowledge(self.items[row]["id"], data)
            QMessageBox.information(self, "同步完成", outcome.get("message", "已同步到知识库"))

    def delete(self):
        row = self.list.currentRow()
        if row < 0 or not self.service:
            return
        answer = QMessageBox.question(self, "确认", f"确定删除“{self.items[row].get('title') or '该 Prompt'}”？")
        if answer == QMessageBox.Yes:
            self.service.delete_prompt(self.items[row]["id"])
            self.refresh()
