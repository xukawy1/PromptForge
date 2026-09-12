
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QListWidget,QLineEdit,QPushButton,QTextEdit,QDialog,QFormLayout,QDialogButtonBox
import json
class PatternDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("新增 Prompt Pattern");f=QFormLayout(self)
        self.name=QLineEdit();self.steps=QLineEdit();self.desc=QTextEdit();f.addRow("名称",self.name);f.addRow("步骤（逗号分隔）",self.steps);f.addRow("说明",self.desc)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(self.accept);b.rejected.connect(self.reject);f.addRow(b)
class PatternsPage(QWidget):
    def __init__(self,app):
        super().__init__();self.app=app;self.s=app.pattern_service;self.rows=[]
        root=QHBoxLayout(self);left=QVBoxLayout();self.list=QListWidget();left.addWidget(self.list);b=QPushButton("新增 Pattern");b.clicked.connect(self.add);left.addWidget(b);root.addLayout(left,2)
        self.detail=QTextEdit();self.detail.setReadOnly(True);root.addWidget(self.detail,3);self.refresh();self.list.currentRowChanged.connect(self.show)
    def refresh(self):
        self.rows=self.s.patterns.list_all();self.list.clear()
        for x in self.rows:self.list.addItem(x["name"])
    def show(self,i):
        if 0<=i<len(self.rows):
            x=self.rows[i]
            try:steps=json.loads(x["pattern_structure"])
            except:steps=[]
            self.detail.setPlainText("步骤：\n"+" → ".join(steps)+"\n\n说明："+(x.get("description") or "")+"\n\n示例："+(x.get("example_prompt") or ""))
    def add(self):
        d=PatternDialog(self)
        if d.exec() and d.name.text().strip():
            self.s.create_pattern(d.name.text().strip(),[x.strip() for x in d.steps.text().split(",") if x.strip()],d.desc.toPlainText());self.refresh()
