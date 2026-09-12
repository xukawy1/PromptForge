from pathlib import Path
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QComboBox, QLabel, QGroupBox,
    QPushButton, QColorDialog, QFileDialog, QCheckBox, QHBoxLayout,
    QMessageBox,
)
from app.core.constants import THEME_MODES, ACCENT_COLORS, APP_VERSION


class SettingsPage(QWidget):
    def __init__(self, config, on_theme_changed, task_manager=None):
        super().__init__()
        self.config = config
        self.on_theme_changed = on_theme_changed
        self.task_manager = task_manager

        layout = QVBoxLayout(self)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        theme_group = QGroupBox("界面主题")
        form = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        for key, name in THEME_MODES.items():
            self.theme_combo.addItem(name, key)
        current_theme = self.config.get("theme_mode", "system")
        idx = self.theme_combo.findData(current_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        form.addRow("主题模式：", self.theme_combo)

        self.accent_combo = QComboBox()
        for key, (name, _) in ACCENT_COLORS.items():
            self.accent_combo.addItem(name, key)
        current_accent = self.config.get("accent_color", "blue")
        idx = self.accent_combo.findData(current_accent)
        if idx >= 0:
            self.accent_combo.setCurrentIndex(idx)
        self.accent_combo.currentIndexChanged.connect(self._accent_changed)
        form.addRow("强调色：", self.accent_combo)

        self.custom_color_btn = QPushButton("自定义强调色…")
        self.custom_color_btn.clicked.connect(self._choose_custom_color)
        form.addRow("", self.custom_color_btn)

        layout.addWidget(theme_group)

        bg_group = QGroupBox("背景图片（按窗口尺寸裁剪铺满整个页面，可调遮罩浓度保证可读性）")
        bg_form = QFormLayout(bg_group)
        path_row = QHBoxLayout()
        self.bg_path_label = QLabel(self.config.get("background_image") or "未设置")
        self.bg_path_label.setStyleSheet("color: #9CA3AF;")
        choose_btn = QPushButton("选择图片…")
        choose_btn.clicked.connect(self._choose_background)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear_background)
        path_row.addWidget(self.bg_path_label, 1)
        path_row.addWidget(choose_btn)
        path_row.addWidget(clear_btn)
        apply_bg_btn = QPushButton("保存并应用背景（软件将自动重启刷新）")
        apply_bg_btn.clicked.connect(self._apply_background_restart)
        path_row.addWidget(apply_bg_btn)
        bg_form.addRow("背景文件", path_row)
        from PySide6.QtWidgets import QSlider
        from PySide6.QtCore import Qt
        self.bg_dim = QSlider(Qt.Orientation.Horizontal)
        self.bg_dim.setRange(0, 90)
        self.bg_dim.setValue(max(0, min(90, int(self.config.get("background_dim_value", 45)))))
        self.bg_dim.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.bg_dim.setTickInterval(10)
        self.bg_dim.valueChanged.connect(self._dim_changed)
        self.bg_dim_label = QLabel(f"{self.bg_dim.value()}%（0=原图，越高越容易看清文字）")
        dim_row = QHBoxLayout()
        dim_row.addWidget(self.bg_dim, 1)
        dim_row.addWidget(self.bg_dim_label)
        bg_form.addRow("遮罩浓度", dim_row)
        bg_form.addRow("建议尺寸", QLabel("与窗口比例一致即可（默认窗口约 1280×800）；任何尺寸都会自动裁剪铺满。"))
        layout.addWidget(bg_group)

        about_group = QGroupBox("关于")
        about_form = QFormLayout(about_group)
        about_form.addRow("程序版本：", QLabel(f"PromptForge {APP_VERSION}"))
        about_form.addRow("数据目录：", QLabel(str(Path(self.config.path).parent)))
        layout.addWidget(about_group)

        note = QLabel(
            "主题模式、强调色与背景会自动保存。强调色作用于按钮、列表选中、进度条等控件；"
            "背景图片在页面留白处显示，内容卡片保持底色以确保可读性。"
        )
        note.setWordWrap(True)
        note.setObjectName("panelHint")
        layout.addWidget(note)

        layout.addStretch()

    def _theme_changed(self):
        self.config.set("theme_mode", self.theme_combo.currentData())
        self.on_theme_changed()

    def _accent_changed(self):
        self.config.set("accent_color", self.accent_combo.currentData())
        self.on_theme_changed()

    def _choose_custom_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.config.set("custom_accent_color", color.name())
            self.config.set("accent_color", "custom")
            self.on_theme_changed()

    def _choose_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择背景图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        self.config.set("background_image", path)
        self.bg_path_label.setText(path)
        self.on_theme_changed()

    def _clear_background(self):
        self.config.set("background_image", "")
        self.bg_path_label.setText("未设置")
        self.on_theme_changed()

    def _apply_background_restart(self):
        if self.task_manager:
            running = self.task_manager.running_count()
            if running > 0:
                QMessageBox.warning(
                    self, "任务进行中",
                    f"还有 {running} 个任务正在执行，暂不能更换背景。\n"
                    "请等任务完成（可在历史记录页确认）后再点击“保存并应用背景”。")
                return
        answer = QMessageBox.question(
            self, "应用背景",
            "背景设置已保存。软件将自动重启一次以加载新背景，是否继续？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        import sys
        import os
        from PySide6.QtWidgets import QApplication
        self.config.save()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "main.py"
            cmd = [sys.executable, script]
        subprocess.Popen(cmd, close_fds=True)
        QApplication.instance().quit()

    def _dim_changed(self, value):
        self.bg_dim_label.setText(f"{value}%（0=原图，越高越容易看清文字）")
        if hasattr(self.config, "set"):
            self.config.set("background_dim_value", int(value))
        if self.config.get("background_image"):
            self.on_theme_changed()
