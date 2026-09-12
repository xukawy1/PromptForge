
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QListWidget,QLabel,QTextEdit,QLineEdit,QPushButton,QDialog,QFormLayout,QDialogButtonBox
class VariantDialog(QDialog):
    def __init__(self, service, component_id, parent=None):
        super().__init__(parent); self.service=service; self.component_id=component_id; self.setWindowTitle("新增组件写法"); f=QFormLayout(self)
        self.text=QLineEdit(); self.lang=QLineEdit("en"); self.style=QLineEdit()
        f.addRow("写法",self.text); f.addRow("语言",self.lang); f.addRow("风格",self.style)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); b.accepted.connect(self.accept); b.rejected.connect(self.reject); f.addRow(b)
    def data(self):return {"component_id":self.component_id,"variant_text":self.text.text().strip(),"language":self.lang.text().strip(),"style":self.style.text().strip(),"confidence":0.0,"usage_count":0}
class ComponentsPage(QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.repo=app.knowledge_service.components; self.service=app.knowledge_service; self.items=[]
        root=QHBoxLayout(self); left=QVBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("搜索组件…"); left.addWidget(self.search); self.list=QListWidget(); self.list.currentRowChanged.connect(self.show); left.addWidget(self.list); root.addLayout(left,2)
        right=QVBoxLayout(); self.name=QLabel("Prompt组件"); self.name.setStyleSheet("font-size:18px;font-weight:bold"); self.detail=QTextEdit(); self.detail.setReadOnly(True); self.addv=QPushButton("新增写法 Variant"); self.addv.clicked.connect(self.add_variant); right.addWidget(self.name); right.addWidget(self.detail); right.addWidget(self.addv); root.addLayout(right,3); self.refresh()
    def refresh(self):
        key=self.search.text().lower(); self.items=[x for x in self.repo.list_all() if not key or key in (x.get("canonical_name") or "").lower() or key in (x.get("name_zh") or "").lower()]; self.list.clear()
        for x in self.items:self.list.addItem(x.get("name_zh") or x.get("canonical_name") or "(未命名)")
    def show(self,row):
        if 0<=row<len(self.items):
            x=self.items[row]; vs=self.service.component_variants(x["id"]); variants="\n".join("• "+(v.get("variant_text") or "") for v in vs) or "暂无变体"
            self.name.setText(x.get("name_zh") or x.get("canonical_name") or "Prompt组件"); self.detail.setPlainText(f"英文：{x.get('name_en') or ''}\n\n说明：{x.get('description') or ''}\n\n使用场景：{x.get('usage_context') or ''}\n\n写法变体：\n{variants}")
    def add_variant(self):
        r=self.list.currentRow()
        if r<0:return
        d=VariantDialog(self.service,self.items[r]["id"],self)
        if d.exec() and d.text.text().strip(): self.service.variants.create(d.data()); self.show(r)
