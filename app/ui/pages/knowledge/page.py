from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QTreeWidget,QTreeWidgetItem,QLineEdit,QPushButton,QListWidget,QLabel,QTextEdit,QDialog,QFormLayout,QDialogButtonBox,QComboBox,QMessageBox

class KnowledgeDialog(QDialog):
    def __init__(self, service, item=None, parent=None):
        super().__init__(parent); self.service=service; self.item=item or {}; self.setWindowTitle("编辑知识" if item else "新增知识"); self.resize(650,520)
        f=QFormLayout(self); self.title=QLineEdit(self.item.get("title", "")); self.summary=QLineEdit(self.item.get("summary", "")); self.typ=QLineEdit(self.item.get("knowledge_type", "general")); self.content=QTextEdit(self.item.get("content", "")); self.cat=QComboBox(); self.cat.addItem("未分类",None)
        for c in service.categories.list(limit=1000,order_by="sort_order ASC,id ASC"): self.cat.addItem(c["name"],c["id"])
        if self.item.get("category_id") is not None:
            i=self.cat.findData(self.item["category_id"]); self.cat.setCurrentIndex(max(i,0))
        f.addRow("标题",self.title); f.addRow("分类",self.cat); f.addRow("摘要",self.summary); f.addRow("类型",self.typ); f.addRow("内容",self.content)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); b.accepted.connect(self.accept); b.rejected.connect(self.reject); f.addRow(b)
    def data(self): return {"title":self.title.text().strip(),"category_id":self.cat.currentData(),"summary":self.summary.text().strip(),"knowledge_type":self.typ.text().strip() or "general","content":self.content.toPlainText()}

class KnowledgePage(QWidget):
    def __init__(self, service=None, generation_service=None, task_manager=None):
        super().__init__(); self.service=service; self.generation_service=generation_service; self.task_manager=task_manager; self.items=[]; self.category_id=None; self._translate_tasks={}
        root=QHBoxLayout(self); left=QVBoxLayout(); self.tree=QTreeWidget(); self.tree.setHeaderLabel("知识分类"); self.tree.itemClicked.connect(self.pick_category); left.addWidget(self.tree); self.newcat=QPushButton("新增分类"); self.newcat.clicked.connect(self.add_category); left.addWidget(self.newcat); root.addLayout(left,1)
        mid=QVBoxLayout(); bar=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("搜索知识…"); b=QPushButton("搜索"); b.clicked.connect(self.load); bar.addWidget(self.search); bar.addWidget(b); imp=QPushButton("导入内置提示词包"); imp.clicked.connect(self.import_builtin); bar.addWidget(imp); mid.addLayout(bar); self.list=QListWidget(); self.list.currentRowChanged.connect(self.show); mid.addWidget(self.list); buttons=QHBoxLayout();
        for text,slot in (("新增",self.add),("编辑",self.edit),("删除",self.delete)):
            x=QPushButton(text); x.clicked.connect(slot); buttons.addWidget(x)
        mid.addLayout(buttons); root.addLayout(mid,2)
        right=QVBoxLayout(); self.title=QLabel("知识详情"); self.title.setObjectName("sectionTitle"); self.detail=QTextEdit(); self.detail.setReadOnly(True)
        right.addWidget(self.title); right.addWidget(self.detail,1)
        trans_label=QLabel("划词翻译：先用鼠标在正文中选中一段文字"); trans_label.setObjectName("sectionTitle")
        self.trans_source=QLabel("（未选中文字）"); self.trans_source.setObjectName("panelHint"); self.trans_source.setWordWrap(True)
        self.detail.selectionChanged.connect(self._on_selection_changed)
        trans_row=QHBoxLayout(); trans_row.addWidget(QLabel("翻译为")); self.trans_lang=QComboBox()
        if self.generation_service:
            for lang in self.generation_service.TRANSLATION_LANGUAGES: self.trans_lang.addItem(lang)
        self.trans_btn=QPushButton("一键翻译"); self.trans_btn.clicked.connect(self.translate_selection)
        trans_row.addWidget(self.trans_lang,1); trans_row.addWidget(self.trans_btn); trans_row.addStretch()
        self.trans_result=QTextEdit(); self.trans_result.setReadOnly(True); self.trans_result.setMaximumHeight(90)
        self.trans_result.setPlaceholderText("翻译结果将显示在这里（需要已在模型中心设置默认 LLM）")
        right.addWidget(trans_label); right.addWidget(self.trans_source); right.addLayout(trans_row); right.addWidget(self.trans_result)
        root.addLayout(right,3); self.refresh()
        if self.task_manager:
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)
    def refresh(self):
        self.tree.clear()
        def add(parent,nodes):
            for n in nodes:
                i=QTreeWidgetItem([n["name"]]); i.setData(0,Qt.UserRole,n["id"]); parent.addChild(i); add(i,n["children"])
        for n in self.service.category_tree():
            i=QTreeWidgetItem([n["name"]]); i.setData(0,Qt.UserRole,n["id"]); self.tree.addTopLevelItem(i); add(i,n["children"])
        self.load()
    def pick_category(self,item,_): self.category_id=item.data(0,Qt.UserRole); self.load()
    def load(self):
        if not self.service:return
        self.items=self.service.list_knowledge(self.category_id,self.search.text()); self.list.clear(); self.list.addItems([x.get("title") or "(未命名知识)" for x in self.items])
    def _on_selection_changed(self):
        cursor = self.detail.textCursor()
        selected = cursor.selectedText().strip()
        if selected:
            self.trans_source.setText("已选中 " + str(len(selected)) + " 字：" + selected[:80] + ("…" if len(selected) > 80 else ""))
        else:
            self.trans_source.setText("（未选中文字）")

    def translate_selection(self):
        cursor = self.detail.textCursor()
        selected = cursor.selectedText().strip()
        if not selected:
            self.trans_result.setPlainText("请先用鼠标在正文中选中要翻译的文字。")
            return
        if not self.generation_service:
            self.trans_result.setPlainText("翻译服务尚未初始化。")
            return
        target = self.trans_lang.currentText() if self.trans_lang.count() else "中文（简体）"
        self.trans_btn.setEnabled(False)
        self.trans_result.setPlainText(f"正在翻译为 {target}……")
        if not self.task_manager:
            try:
                self.trans_result.setPlainText(self.generation_service.translate(selected, target))
            except Exception as exc:
                self.trans_result.setPlainText(f"翻译失败：{exc}")
            finally:
                self.trans_btn.setEnabled(True)
            return
        if self._translate_tasks:
            self.trans_result.setPlainText("已有翻译任务在执行。")
            self.trans_btn.setEnabled(True)
            return
        def worker(ctx):
            ctx.report_progress(40)
            return self.generation_service.translate(selected, target)
        task_id, future, ctx = self.task_manager.submit(fn=worker, task_type="knowledge.translate", input_data={"label": "划词翻译"})
        self._translate_tasks[task_id] = target

    def _on_task_finished(self, task_id, result):
        if task_id in self._translate_tasks:
            self._translate_tasks.pop(task_id)
            self.trans_btn.setEnabled(True)
            self.trans_result.setPlainText(str(result))

    def _on_task_failed(self, task_id, message):
        if task_id in self._translate_tasks:
            self._translate_tasks.pop(task_id)
            self.trans_btn.setEnabled(True)
            self.trans_result.setPlainText(f"翻译失败：{message}")

    def show(self,row):
        if 0<=row<len(self.items): x=self.items[row]; self.title.setText(x.get("title") or "知识详情"); self.detail.setPlainText((x.get("summary") or "")+"\n\n"+(x.get("content") or ""))
    def showEvent(self, event):
        super().showEvent(event)
        self.load()

    def import_builtin(self):
        if not self.service: return
        from app.services.seed_content_service import SeedContentService
        from PySide6.QtWidgets import QMessageBox
        try:
            outcome = SeedContentService(self.service.db).import_builtin()
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc)); return
        QMessageBox.information(self, "导入完成",
                                f"新增知识卡片 {outcome['knowledge_cards']} 张，成品 Prompt {outcome['prompts']} 条。"
                                + "\n成品提示词已同步进 Prompt 库；重复点击只会补缺，不会重复导入。")
        self.load()

    def add(self):
        d=KnowledgeDialog(self.service,parent=self)
        if d.exec() and d.data()["title"]: self.service.create_knowledge(d.data()); self.load()
    def edit(self):
        r=self.list.currentRow()
        if r<0:return
        d=KnowledgeDialog(self.service,self.items[r],self)
        if d.exec(): self.service.update_knowledge(self.items[r]["id"],d.data()); self.load()
    def delete(self):
        r=self.list.currentRow()
        if r>=0 and QMessageBox.question(self,"确认","确定删除当前知识？")==QMessageBox.Yes: self.service.delete_knowledge(self.items[r]["id"]); self.load()
    def add_category(self):
        d=QDialog(self); d.setWindowTitle("新增分类"); f=QFormLayout(d); name=QLineEdit(); parent=QComboBox(); parent.addItem("顶级分类",None)
        for c in self.service.categories.list(limit=1000,order_by="sort_order ASC,id ASC"): parent.addItem(c["name"],c["id"])
        f.addRow("名称",name); f.addRow("父分类",parent); b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); b.accepted.connect(d.accept); b.rejected.connect(d.reject); f.addRow(b)
        if d.exec() and name.text().strip(): self.service.categories.create({"name":name.text().strip(),"parent_id":parent.currentData()}); self.refresh()
