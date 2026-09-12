
from PySide6.QtWidgets import QWidget,QVBoxLayout,QPushButton,QLabel,QFileDialog,QMessageBox
class DataToolsPage(QWidget):
    def __init__(self,app):
        super().__init__();self.app=app;l=QVBoxLayout(self);l.addWidget(QLabel("数据维护与完整性"))
        b=QPushButton("检查数据库完整性");b.clicked.connect(self.check);l.addWidget(b)
        e=QPushButton("导出知识库 JSON");e.clicked.connect(self.export);l.addWidget(e)
    def check(self):
        r=self.app.phase2_finalize.integrity_check();QMessageBox.information(self,"检查结果","数据库完整，无孤儿关联。" if r["ok"] else "发现问题：\n"+"\n".join(r["problems"]))
    def export(self):
        p,_=QFileDialog.getSaveFileName(self,"导出知识库","","JSON (*.json)")
        if p:self.app.phase2_finalize.export_json(p);QMessageBox.information(self,"完成","知识库已导出。")
