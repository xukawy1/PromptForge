
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QListWidget,QLabel,QTextEdit,QLineEdit,QPushButton,QDialog,QFormLayout,QDialogButtonBox,QCheckBox,QTableWidget,QTableWidgetItem
from PySide6.QtCore import Qt
class TemplateDialog(QDialog):
    def __init__(self,service,item=None,parent=None):
        super().__init__(parent);self.service=service;self.item=item or {};self.setWindowTitle("编辑模板" if item else "新增模板");self.resize(800,650)
        root=QVBoxLayout(self);f=QFormLayout();self.name=QLineEdit(self.item.get("name",""));self.desc=QLineEdit(self.item.get("description",""));self.content=QTextEdit(self.item.get("template_content",""));self.model=QLineEdit(self.item.get("target_model",""));self.lang=QLineEdit(self.item.get("language","en"));self.version=QLineEdit(self.item.get("version","1.0"))
        for n,w in [("名称",self.name),("说明",self.desc),("模板正文",self.content),("目标模型",self.model),("语言",self.lang),("版本",self.version)]:f.addRow(n,w)
        root.addLayout(f);root.addWidget(QLabel("变量（每行：变量名 | 显示名 | 默认值 | 必填）"))
        self.vars=QTableWidget(0,4);self.vars.setHorizontalHeaderLabels(["变量名","显示名","默认值","必填"]);root.addWidget(self.vars)
        add=QPushButton("添加变量");add.clicked.connect(self.add_var);root.addWidget(add)
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(self.accept);b.rejected.connect(self.reject);root.addWidget(b)
        for v in service.variables(self.item["id"]) if self.item else []:self.add_var(v)
    def add_var(self,v=None):
        r=self.vars.rowCount();self.vars.insertRow(r)
        vals=[(v or {}).get("variable_name",""),(v or {}).get("display_name",""),(v or {}).get("default_value",""),"1" if (v or {}).get("required") else "0"]
        for i,x in enumerate(vals):self.vars.setItem(r,i,QTableWidgetItem(str(x)))
    def data(self):
        vars=[]
        for r in range(self.vars.rowCount()):
            vals=[self.vars.item(r,c).text().strip() if self.vars.item(r,c) else "" for c in range(4)]
            if vals[0]:vars.append({"variable_name":vals[0],"display_name":vals[1] or vals[0],"default_value":vals[2],"required":vals[3] in ("1","true","是","yes")})
        return {"name":self.name.text().strip(),"description":self.desc.text().strip(),"template_content":self.content.toPlainText(),"target_model":self.model.text().strip(),"language":self.lang.text().strip(),"version":self.version.text().strip(),"variables":vars}
class TemplatesPage(QWidget):
    def __init__(self,app):
        super().__init__();self.app=app;self.s=app.pattern_service;self.rows=[]
        root=QHBoxLayout(self);left=QVBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText("搜索模板…");left.addWidget(self.search);self.list=QListWidget();left.addWidget(self.list);bs=QHBoxLayout()
        for label,fn in [("新增",self.add),("编辑",self.edit),("删除",self.delete)]:b=QPushButton(label);b.clicked.connect(fn);bs.addWidget(b)
        left.addLayout(bs);root.addLayout(left,2);right=QVBoxLayout();self.title=QLabel("Prompt模板");self.title.setStyleSheet("font-size:18px;font-weight:bold");self.detail=QTextEdit();self.detail.setReadOnly(True);right.addWidget(self.title);right.addWidget(self.detail);root.addLayout(right,3);self.refresh();self.list.currentRowChanged.connect(self.show)
    def refresh(self):
        k=self.search.text().lower();self.rows=[x for x in self.s.templates.list_all() if not k or k in (x.get("name") or "").lower()];self.list.clear()
        for x in self.rows:self.list.addItem(x.get("name") or "(未命名)")
    def show(self,i):
        if 0<=i<len(self.rows):
            x=self.rows[i];vs=self.s.variables(x["id"]);self.title.setText(x.get("name") or "Prompt模板");self.detail.setPlainText((x.get("description") or "")+"\n\n"+(x.get("template_content") or "")+"\n\n变量："+", ".join(v["variable_name"] for v in vs))
    def add(self):
        d=TemplateDialog(self.s,self); 
        if d.exec() and d.name.text().strip():x=d.data();self.s.create_template({k:v for k,v in x.items() if k!="variables"},x["variables"]);self.refresh()
    def edit(self):
        i=self.list.currentRow()
        if i<0:return
        d=TemplateDialog(self.s,self.rows[i],self)
        if d.exec():
            x=d.data();tid=self.rows[i]["id"];self.s.templates.update(tid,{k:v for k,v in x.items() if k!="variables"})
            self.s.template_components.delete(tid) if False else None
            self.refresh()
    def delete(self):
        i=self.list.currentRow()
        if i>=0:self.s.templates.delete(self.rows[i]["id"]);self.refresh()
