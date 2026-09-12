
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QListWidget,QLineEdit,QPushButton,QTextEdit,QLabel,QDialog,QFormLayout,QComboBox,QDialogButtonBox,QMessageBox,QCheckBox
from PySide6.QtCore import Qt

class PromptEditDialog(QDialog):
    def __init__(self, service, item=None, parent=None):
        super().__init__(parent); self.service=service; self.item=item or {}; self.setWindowTitle("编辑 Prompt" if item else "新增 Prompt"); self.resize(720,620)
        f=QFormLayout(self); self.title=QLineEdit(self.item.get("title","")); self.text=QTextEdit(self.item.get("prompt_text",""))
        self.neg=QTextEdit(self.item.get("negative_prompt","")); self.typ=QLineEdit(self.item.get("prompt_type","image"))
        self.model=QLineEdit(self.item.get("target_model","")); self.lang=QLineEdit(self.item.get("language",""))
        self.source=QComboBox(); self.source.addItem("无来源",None); self.source_ids=[]
        for s in service.sources.list_all(): self.source.addItem(s.get("title") or s.get("url") or f"来源#{s['id']}",s["id"]); self.source_ids.append(s["id"])
        if self.item.get("source_id") in self.source_ids:self.source.setCurrentIndex(self.source_ids.index(self.item["source_id"])+1)
        for lab,w in [("标题",self.title),("Prompt",self.text),("Negative Prompt",self.neg),("类型",self.typ),("目标模型",self.model),("语言",self.lang),("来源",self.source)]: f.addRow(lab,w)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); b.accepted.connect(self.accept); b.rejected.connect(self.reject); f.addRow(b)
    def data(self):
        return {"title":self.title.text().strip(),"prompt_text":self.text.toPlainText().strip(),"negative_prompt":self.neg.toPlainText().strip(),
                "prompt_type":self.typ.text().strip() or "image","target_model":self.model.text().strip(),
                "language":self.lang.text().strip() or "en","source_id":self.source.currentData()}

class PromptsPage(QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.service=app.knowledge_service; self.items=[]
        root=QHBoxLayout(self); left=QVBoxLayout(); bar=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("搜索 Prompt…"); b=QPushButton("搜索"); b.clicked.connect(self.refresh); bar.addWidget(self.search); bar.addWidget(b); left.addLayout(bar)
        self.list=QListWidget(); self.list.currentRowChanged.connect(self.show); left.addWidget(self.list)
        bs=QHBoxLayout()
        for label,fn in [("新增",self.add),("编辑",self.edit),("删除",self.delete)]:
            x=QPushButton(label); x.clicked.connect(fn); bs.addWidget(x)
        left.addLayout(bs); root.addLayout(left,2)
        right=QVBoxLayout(); self.title=QLabel("Prompt详情"); self.title.setStyleSheet("font-size:18px;font-weight:bold"); self.detail=QTextEdit(); self.detail.setReadOnly(True)
        self.trace=QLabel("来源：无"); self.trace.setWordWrap(True); right.addWidget(self.title); right.addWidget(self.trace); right.addWidget(self.detail); root.addLayout(right,3); self.refresh()
    def refresh(self):
        r=self.service.search_prompts(self.search.text()); self.items=r["items"]; self.list.clear()
        for x in self.items:self.list.addItem(x.get("title") or "(未命名 Prompt)")
    def show(self,row):
        if not 0<=row<len(self.items):return
        x=self.items[row]; self.title.setText(x.get("title") or "Prompt详情")
        self.detail.setPlainText((x.get("prompt_text") or "")+"\n\nNegative Prompt:\n"+(x.get("negative_prompt") or "")+"\n\n类型："+(x.get("prompt_type") or "")+"\n目标模型："+(x.get("target_model") or ""))
        tr=self.service.prompt_source_trace(x["id"]); s=tr.get("source") if tr else None; im=tr.get("image") if tr else None
        self.trace.setText("来源："+(s.get("title") or s.get("url") or f"来源#{s['id']}") if s else "来源：无")
        if im:self.trace.setText(self.trace.text()+"\n图片："+(im.get("file_path") or f"图片#{im['id']}"))
    def add(self):
        d=PromptEditDialog(self.service,parent=self)
        if d.exec():self.service.create_prompt(d.data());self.refresh()
    def edit(self):
        r=self.list.currentRow()
        if r<0:return
        d=PromptEditDialog(self.service,self.items[r],self)
        if d.exec():self.service.update_prompt(self.items[r]["id"],d.data());self.refresh()
    def delete(self):
        r=self.list.currentRow()
        if r<0:return
        if QMessageBox.question(self,"确认","确定删除该 Prompt？")==QMessageBox.Yes:self.service.delete_prompt(self.items[r]["id"]);self.refresh()
