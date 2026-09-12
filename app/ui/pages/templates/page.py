from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QLineEdit, QPushButton,
    QLabel, QTextEdit, QDialog, QFormLayout, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QMessageBox,
)


class TemplateDialog(QDialog):
    def __init__(self, pattern_service=None, item=None, parent=None):
        super().__init__(parent)
        self.pattern_service = pattern_service
        self.item = item or {}
        self.setWindowTitle("编辑模板" if item else "新增模板")
        self.resize(720, 560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(self.item.get("name", ""))
        self.description = QLineEdit(self.item.get("description", ""))
        self.content = QTextEdit(self.item.get("template_content", ""))
        self.model = QLineEdit(self.item.get("target_model", ""))
        self.language = QLineEdit(self.item.get("language", "en"))
        self.version = QLineEdit(str(self.item.get("version", "1.0")))
        for label, widget in (("名称（必填）", self.name), ("说明", self.description), ("模板正文", self.content),
                              ("目标模型", self.model), ("语言", self.language), ("版本", self.version)):
            form.addRow(label, widget)
        root.addLayout(form)
        root.addWidget(QLabel("变量（每行一个：变量名 | 显示名 | 默认值 | 必填1/0）"))
        self.vars = QTableWidget(0, 4)
        self.vars.setHorizontalHeaderLabels(["变量名", "显示名", "默认值", "必填"])
        root.addWidget(self.vars)
        add_var_btn = QPushButton("添加变量行")
        add_var_btn.clicked.connect(lambda: self.add_var())
        root.addWidget(add_var_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for v in self.pattern_service.variables(self.item["id"]) if (self.pattern_service and self.item) else []:
            self.add_var(v)

    def add_var(self, v=None):
        row = self.vars.rowCount()
        self.vars.insertRow(row)
        values = [
            (v or {}).get("variable_name", ""),
            (v or {}).get("display_name", ""),
            (v or {}).get("default_value", "") or "",
            "1" if (v or {}).get("required") else "0",
        ]
        for col, value in enumerate(values):
            self.vars.setItem(row, col, QTableWidgetItem(str(value)))

    def data(self):
        variables = []
        for row in range(self.vars.rowCount()):
            values = [(self.vars.item(row, col).text().strip() if self.vars.item(row, col) else "") for col in range(4)]
            if values[0]:
                variables.append({
                    "variable_name": values[0],
                    "display_name": values[1] or values[0],
                    "default_value": values[2],
                    "required": values[3] in ("1", "true", "是", "yes"),
                })
        return {
            "name": self.name.text().strip(),
            "description": self.description.text().strip() or None,
            "template_content": self.content.toPlainText(),
            "target_model": self.model.text().strip() or None,
            "language": self.language.text().strip() or "en",
            "version": self.version.text().strip() or "1.0",
            "variables": variables,
        }


class TemplatesPage(QWidget):
    def __init__(self, service=None, pattern_service=None):
        super().__init__()
        self.service = service
        self.pattern_service = pattern_service
        self.items = []
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        hint = QLabel(
            "页面说明：模板 = 带变量占位符（如 {subject}）的提示词骨架，可复用于 Prompt 生成页。\n"
            "用法：新增模板并写入正文 → 为每个变量命名并给默认值 → 在 Prompt生成页选择该模板、填变量即可一键套用。"
        )
        hint.setObjectName("panelHint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索模板…")
        self.search.returnPressed.connect(self.refresh)
        left.addWidget(self.search)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        left.addWidget(refresh_btn)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show)
        left.addWidget(self.list)
        buttons = QHBoxLayout()
        for label, slot in (("新增模板", self.add), ("编辑", self.edit), ("删除", self.delete)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        buttons.addStretch()
        left.addLayout(buttons)
        root.addLayout(left, 2)

        right = QVBoxLayout()
        self.title = QLabel("Prompt模板")
        self.title.setStyleSheet("font-size:18px;font-weight:700")
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right.addWidget(self.title)
        right.addWidget(self.detail)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        right.addWidget(self.result)
        root.addLayout(right, 3)
        self.refresh()

    def refresh(self):
        self.items = []
        if self.pattern_service:
            self.items = self.pattern_service.templates.list(200)
        key = self.search.text().strip().lower()
        self.items = [x for x in self.items if not key or key in (x.get("name") or "").lower()]
        self.list.clear()
        self.list.addItems([x.get("name") or "(未命名模板)" for x in self.items])

    def show(self, row):
        if 0 <= row < len(self.items) and self.pattern_service:
            x = self.items[row]
            comps = self.pattern_service.variables(x["id"])
            variables = "\n".join(f"• {{{c['variable_name']}}} — {c['display_name']}" for c in comps) or "暂无变量"
            mark = "（系统预置）" if x.get("is_system") else ""
            self.title.setText((x.get("name") or "Prompt模板") + mark)
            self.detail.setPlainText(f"说明：{x.get('description') or ''}\n目标模型：{x.get('target_model') or ''}\n版本：{x.get('version') or 1}\n\n变量：\n{variables}\n\n模板正文：\n{x.get('template_content') or ''}")

    def _current(self):
        row = self.list.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def add(self):
        if not self.pattern_service:
            return
        dialog = TemplateDialog(self.pattern_service, parent=self)
        if dialog.exec() and dialog.data()["name"]:
            data = dialog.data()
            self.pattern_service.create_template(
                {k: v for k, v in data.items() if k != "variables"}, data["variables"]
            )
            self.result.setText("模板已创建。")
            self.refresh()

    def edit(self):
        template = self._current()
        if not template or not self.pattern_service:
            self.result.setText("请先选择模板。")
            return
        if template.get("is_system"):
            self.result.setText("系统预置模板不可编辑；可复制内容新建模板。")
            return
        dialog = TemplateDialog(self.pattern_service, template, self)
        if dialog.exec() and dialog.data()["name"]:
            data = dialog.data()
            template_id = template["id"]
            self.pattern_service.templates.update(template_id, {k: v for k, v in data.items() if k != "variables"})
            for v in self.pattern_service.variables(template_id):
                self.pattern_service.template_components.delete(v["id"])
            for i, var in enumerate(data["variables"]):
                self.pattern_service.template_components.create({
                    "template_id": template_id,
                    "variable_name": var["variable_name"],
                    "display_name": var.get("display_name", var["variable_name"]),
                    "required": 1 if var.get("required") else 0,
                    "default_value": var.get("default_value", ""),
                    "sort_order": i,
                })
            self.result.setText("模板已更新。")
            self.refresh()
            self.show(self.list.currentRow())

    def delete(self):
        template = self._current()
        if not template or not self.pattern_service:
            return
        if template.get("is_system"):
            self.result.setText("系统预置模板不可删除。")
            return
        answer = QMessageBox.question(self, "确认", f"确定删除模板“{template.get('name')}”？")
        if answer == QMessageBox.Yes:
            self.pattern_service.templates.delete(template["id"])
            self.result.setText("模板已删除。")
            self.refresh()
