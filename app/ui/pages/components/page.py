from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLineEdit, QPushButton,
    QLabel, QTextEdit, QDialog, QFormLayout, QDialogButtonBox, QComboBox,
    QMessageBox,
)


class ComponentDialog(QDialog):
    def __init__(self, service=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增 Prompt 组件")
        form = QFormLayout(self)
        self.canonical = QLineEdit()
        self.name_zh = QLineEdit()
        self.name_en = QLineEdit()
        self.category = QComboBox()
        self.category.addItem("未分类", None)
        if service:
            for c in service.categories.list(1000, order_by="sort_order ASC,id ASC"):
                self.category.addItem(c["name"], c["id"])
        self.description = QLineEdit()
        self.usage = QLineEdit()
        form.addRow("标准名（必填）", self.canonical)
        form.addRow("中文名", self.name_zh)
        form.addRow("英文名", self.name_en)
        form.addRow("分类", self.category)
        form.addRow("说明", self.description)
        form.addRow("使用场景", self.usage)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self):
        return {
            "canonical_name": self.canonical.text().strip(),
            "name_zh": self.name_zh.text().strip() or None,
            "name_en": self.name_en.text().strip() or None,
            "category_id": self.category.currentData(),
            "description": self.description.text().strip() or None,
            "usage_context": self.usage.text().strip() or None,
        }


class VariantDialog(QDialog):
    def __init__(self, component_id, parent=None):
        super().__init__(parent)
        self.component_id = component_id
        self.setWindowTitle("新增写法 Variant")
        form = QFormLayout(self)
        self.text = QLineEdit()
        self.language = QLineEdit("en")
        self.style = QLineEdit()
        form.addRow("写法（必填）", self.text)
        form.addRow("语言", self.language)
        form.addRow("风格", self.style)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def data(self):
        return {
            "component_id": self.component_id,
            "variant_text": self.text.text().strip(),
            "language": self.language.text().strip() or None,
            "style": self.style.text().strip() or None,
            "confidence": 0.0,
            "usage_count": 0,
        }


class ComponentsPage(QWidget):
    def __init__(self, service=None):
        super().__init__()
        self.service = service
        self.items = []
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        hint = QLabel(
            "页面说明：这里沉淀你收集到的提示词要素（如光线、镜头、风格等），每个组件可保存多种写法 Variant。\n"
            "用法：搜索/新增组件 → 选中组件后可添加它的不同写法 → 生成 Prompt 时把合适的组件写法组合进需求即可。"
        )
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索组件…")
        self.search.returnPressed.connect(self.refresh)
        left.addWidget(self.search)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        left.addWidget(refresh_btn)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show)
        left.addWidget(self.list)
        root.addLayout(left, 2)

        right = QVBoxLayout()
        self.title = QLabel("Prompt组件")
        self.title.setStyleSheet("font-size:18px;font-weight:700")
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right.addWidget(self.title)
        right.addWidget(self.detail)
        buttons = QHBoxLayout()
        add_btn = QPushButton("新增组件")
        add_btn.clicked.connect(self.add_component)
        variant_btn = QPushButton("新增写法 Variant")
        variant_btn.clicked.connect(self.add_variant)
        delete_btn = QPushButton("删除组件")
        delete_btn.clicked.connect(self.delete_component)
        for btn in (add_btn, variant_btn, delete_btn):
            buttons.addWidget(btn)
        buttons.addStretch()
        right.addLayout(buttons)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        right.addWidget(self.result)
        root.addLayout(right, 3)
        self.refresh()

    def refresh(self):
        self.items = self.service.components.search_text(self.search.text(), 200) if self.service else []
        self.list.clear()
        self.list.addItems([x.get("name_zh") or x.get("canonical_name") or "(未命名)" for x in self.items])

    def show(self, row):
        if 0 <= row < len(self.items):
            x = self.items[row]
            variants = self.service.variants.list(200, where="component_id=?", params=(x["id"],), order_by="usage_count DESC,id ASC")
            vs = "\n".join("• " + str(v["variant_text"]) for v in variants) or "暂无变体"
            self.title.setText(x.get("name_zh") or x.get("canonical_name") or "Prompt组件")
            self.detail.setPlainText(f"英文：{x.get('name_en') or ''}\n\n说明：{x.get('description') or ''}\n\n使用场景：{x.get('usage_context') or ''}\n\n写法变体：\n{vs}")

    def _current(self):
        row = self.list.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def add_component(self):
        if not self.service:
            return
        dialog = ComponentDialog(self.service, self)
        if dialog.exec() and dialog.data()["canonical_name"]:
            component_id = self.service.components.create(dialog.data())
            self.result.setText(f"已创建组件 #{component_id}。")
            self.refresh()

    def add_variant(self):
        component = self._current()
        if not component or not self.service:
            self.result.setText("请先选择一个组件。")
            return
        dialog = VariantDialog(component["id"], self)
        if dialog.exec() and dialog.data()["variant_text"]:
            self.service.variants.create(dialog.data())
            self.result.setText("写法已添加。")
            self.show(self.list.currentRow())

    def delete_component(self):
        component = self._current()
        if not component or not self.service:
            return
        answer = QMessageBox.question(self, "确认", f"确定删除组件“{component.get('name_zh') or component.get('canonical_name')}”？其写法将一并删除。")
        if answer == QMessageBox.Yes:
            self.service.components.delete(component["id"])
            self.result.setText("组件已删除。")
            self.refresh()
