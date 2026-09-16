from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication


def _mix(base, accent, ratio):
    """把强调色按比例混入基色，用于生成悬停/边框等派生色。"""
    a = QColor(base)
    b = QColor(accent)
    return "#{:02X}{:02X}{:02X}".format(
        int(a.red() * (1 - ratio) + b.red() * ratio),
        int(a.green() * (1 - ratio) + b.green() * ratio),
        int(a.blue() * (1 - ratio) + b.blue() * ratio),
    )


def build_stylesheet(mode: str, accent_color: str) -> str:
    """生成整套 QSS：亮/暗两套基础色 + 强调色派生控件样式。"""
    dark = mode == "dark"
    window = "#1B1C1F" if dark else "#F3F4F6"
    surface = "#232529" if dark else "#FFFFFF"
    surface2 = "#2A2D33" if dark else "#F9FAFB"
    text = "#ECEEF1" if dark else "#1F2937"
    text_dim = "#9CA3AF" if dark else "#6B7280"
    border = "#33363D" if dark else "#E5E7EB"
    hover = _mix(surface, accent_color, 0.14)
    accent_hover = _mix(accent_color, "#000000", 0.18)
    selection_bg = accent_color

    return f"""
QWidget {{ background: {window}; color: {text}; font-size: 13px; }}
QMainWindow {{ background: {window}; }}

QFrame[card="true"] {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
}}
QFrame[card="true"] QLabel {{ background: transparent; }}

QLabel {{ background: transparent; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; background: transparent; }}
QLabel#pageSubtitle {{ color: {text_dim}; background: transparent; }}
QLabel#panelHint {{ color: {text_dim}; background: transparent; }}
QLabel#sectionTitle {{ font-size: 16px; font-weight: 700; background: transparent; }}

QPushButton {{
    background: {surface2};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 14px;
    color: {text};
}}
QPushButton:hover {{ background: {hover}; border-color: {accent_color}; }}
QPushButton:pressed {{ background: {accent_hover}; color: white; }}
QPushButton:disabled {{ color: {text_dim}; border-color: {border}; }}
QPushButton[primary="true"] {{
    background: {accent_color}; color: white; border: none; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {accent_hover}; }}
QPushButton[danger="true"] {{ color: #EF4444; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 5px 8px;
    color: {text};
    selection-background-color: {selection_bg};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {accent_color};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {surface}; color: {text}; border: 1px solid {border};
    selection-background-color: {accent_color}; selection-color: white;
}}

QListWidget, QTableWidget, QTreeWidget, QListView, QTreeView {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    color: {text};
    alternate-background-color: {surface2};
}}
QListWidget::item, QTreeView::item {{ padding: 4px 6px; border-radius: 4px; }}
QListWidget::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {accent_color}; color: white;
}}
QListWidget#navigation {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
    padding: 6px; font-size: 14px; outline: none;
}}
QListWidget#navigation::item {{ padding: 9px 10px; border-radius: 7px; margin: 2px 0; }}
QListWidget#navigation::item:hover {{ background: {hover}; }}
QListWidget#navigation::item:selected {{ background: {accent_color}; color: white; }}

QTableWidget {{
    gridline-color: {border};
    selection-background-color: {accent_color};
    selection-color: white;
}}
QHeaderView::section {{
    background: {surface2}; color: {text_dim};
    border: none; border-bottom: 1px solid {border};
    padding: 6px 8px; font-weight: 600;
}}

QGroupBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; top: 0px;
    padding: 0 6px; color: {accent_color};
}}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; background: {surface}; }}
QTabBar::tab {{
    background: {surface2}; color: {text_dim};
    padding: 7px 16px; border: 1px solid {border}; border-bottom: none;
    top-left-radius: 6px; top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: {surface}; color: {text}; border-color: {accent_color}; }}

QProgressBar {{
    background: {surface2}; border: 1px solid {border}; border-radius: 7px;
    height: 14px; text-align: center; color: {text_dim};
}}
QProgressBar::chunk {{ background: {accent_color}; border-radius: 6px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {accent_color}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {accent_color}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QMenuBar {{ background: {surface}; color: {text}; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {hover}; border-radius: 4px; }}
QMenu {{
    background: {surface}; color: {text};
    border: 1px solid {border}; border-radius: 8px; padding: 6px;
}}
QMenu::item {{ padding: 6px 26px 6px 14px; border-radius: 5px; background: transparent; color: {text}; }}
QMenu::item:selected {{ background: {accent_color}; color: white; }}
QMenu::item:disabled {{ color: {text_dim}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QSplitter::handle {{ background: {border}; width: 2px; }}
QToolTip {{
    background: {surface}; color: {text};
    border: 1px solid {accent_color}; border-radius: 4px; padding: 4px 8px;
}}
QStatusBar {{ background: {surface}; color: {text_dim}; }}
QMessageBox, QDialog {{ background: {window}; }}
"""


def apply_theme(app: QApplication, mode: str, accent: str, custom_accent=None):
    from app.core.constants import ACCENT_COLORS

    if accent == "custom" and custom_accent:
        accent_color = custom_accent
    else:
        accent_color = ACCENT_COLORS.get(accent, ACCENT_COLORS["blue"])[1]

    if mode == "dark":
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#1B1C1F"))
        palette.setColor(QPalette.WindowText, QColor("#ECEEF1"))
        palette.setColor(QPalette.Base, QColor("#232529"))
        palette.setColor(QPalette.AlternateBase, QColor("#2A2D33"))
        palette.setColor(QPalette.Text, QColor("#ECEEF1"))
        palette.setColor(QPalette.Button, QColor("#2A2D33"))
        palette.setColor(QPalette.ButtonText, QColor("#ECEEF1"))
        palette.setColor(QPalette.ToolTipBase, QColor("#2A2D33"))
        palette.setColor(QPalette.ToolTipText, QColor("#ECEEF1"))
        palette.setColor(QPalette.Highlight, QColor(accent_color))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        app.setPalette(palette)
    else:
        app.setPalette(app.style().standardPalette())
        palette = app.palette()
        palette.setColor(QPalette.Highlight, QColor(accent_color))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        app.setPalette(palette)

    if mode not in ("dark", "light"):
        mode = "light"
    app.setStyleSheet(build_stylesheet(mode, accent_color))


def build_background_overlay(mode: str, accent_color: str) -> str:
    """背景图模式附加样式：页面整体透明露出背景图，内容控件改为半透明浮层。"""
    dark = mode == "dark"
    r, g, b = (35, 37, 41) if dark else (255, 255, 255)
    nl = chr(10)
    window = "#1B1C1F" if dark else "#F3F4F6"
    surface = "#232529" if dark else "#FFFFFF"
    text = "#ECEEF1" if dark else "#1F2937"
    rules = [
        "/*PFBG*/",
        "#pageHost QWidget { background: transparent; }",
        f"#pageHost QDialog, #pageHost QMessageBox {{ background: {window}; }}",
        f"#pageHost QComboBox QAbstractItemView {{ background: {surface}; color: {text}; }}",
        f"#pageHost QMenu, QMenu {{ background: {surface}; color: {text}; border: 1px solid {window}; }}",
        "#pageHost QGroupBox, #pageHost QFrame[card=\"true\"], #pageHost QTextEdit, #pageHost QPlainTextEdit, "
        "#pageHost QLineEdit, #pageHost QListWidget, #pageHost QTableWidget, #pageHost QTreeWidget, "
        "#pageHost QComboBox, #pageHost QSpinBox, #pageHost QProgressBar, #pageHost QTabWidget::pane "
        "{ background: rgba(%d,%d,%d,176); }" % (r, g, b),
        "#pageHost QPushButton { background: rgba(%d,%d,%d,150); }" % (r, g, b),
        "#pageHost QPushButton[primary=\"true\"] { background: %s; }" % accent_color,
        "#pageHost QHeaderView::section { background: rgba(%d,%d,%d,210); }" % (r, g, b),
    ]
    return nl.join(rules) + nl
