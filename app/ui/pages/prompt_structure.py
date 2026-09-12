
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTextEdit,QPushButton,QTreeWidget,QTreeWidgetItem,QLabel
from PySide6.QtCore import Qt

class PromptStructurePage(QWidget):
    def __init__(self,app):
        super().__init__(); self.app=app; self.service=app.knowledge_service
        root=QVBoxLayout(self); root.addWidget(QLabel("Prompt结构化 / Prompt DNA"))
        row=QHBoxLayout(); self.input=QTextEdit(); self.input.setPlaceholderText("输入一段 Prompt，或从 Prompt 库复制…")
        self.tree=QTreeWidget(); self.tree.setHeaderLabels(["结构","内容"])
        row.addWidget(self.input); row.addWidget(self.tree); root.addLayout(row)
        self.dna=QLabel("DNA：-"); self.dna.setWordWrap(True); root.addWidget(self.dna)
        b=QPushButton("分析结构"); b.clicked.connect(self.analyze); root.addWidget(b)
    def analyze(self):
        r=self.service.build_prompt_structure(self.input.toPlainText()); self.tree.clear()
        for s in r["structure"]["slots"]:
            if not s["items"]:continue
            item=QTreeWidgetItem([s["name_zh"],""])
            for v in s["items"]:item.addChild(QTreeWidgetItem(["",v]))
            self.tree.addTopLevelItem(item)
        d=r["dna"];self.dna.setText(f"DNA：{d['signature']}\nHash：{d['hash']}\n结构槽位：{d['slot_count']}")
