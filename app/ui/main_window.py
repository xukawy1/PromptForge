from app.ui.pages.prompt_structure import PromptStructurePage
from app.ui.pages.patterns import PatternsPage
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QLabel
)

from app.ui.pages.dashboard.page import DashboardPage
from app.ui.pages.collector.page import CollectorPage
from app.ui.pages.knowledge.page import KnowledgePage
from app.ui.pages.components.page import ComponentsPage
from app.ui.pages.templates.page import TemplatesPage
from app.ui.pages.prompt_library.page import PromptLibraryPage
from app.ui.pages.skill.page import SkillPage
from app.ui.pages.generator.page import GeneratorPage
from app.ui.pages.image_analysis.page import ImageAnalysisPage
from app.ui.pages.models.page import ModelsPage
from app.ui.pages.history.page import HistoryPage
from app.ui.pages.settings.page import SettingsPage


def _icon_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "resources" / "app_icon.ico"


class MainWindow(QMainWindow):
    def __init__(self, config, apply_theme_callback, dashboard_service=None, knowledge_service=None, collector_service=None, task_manager=None, db_path=None, task_service=None, image_service=None, model_service=None, generation_service=None, pattern_service=None, skill_service=None):
        super().__init__()
        self.config = config
        self.apply_theme_callback = apply_theme_callback
        self.dashboard_service = dashboard_service
        self.knowledge_service = knowledge_service
        self.collector_service = collector_service
        self.task_manager = task_manager
        self.db_path = db_path
        self.task_service = task_service
        self.image_service = image_service
        self.model_service = model_service
        self.generation_service = generation_service
        self.pattern_service = pattern_service
        self.skill_service = skill_service

        self.setWindowTitle("PromptForge · AI提示词知识工坊")
        icon_file = _icon_path()
        if icon_file.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_file)))
        self.resize(1280, 800)
        self.setMinimumSize(1000, 650)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(190)

        self.stack = QStackedWidget()

        pages = [
            ("🏠  工作台", DashboardPage),
            ("📥  采集中心", CollectorPage),
            ("📚  知识库", KnowledgePage),
            ("🧩  Prompt组件", ComponentsPage),
            ("📐  Prompt模板", TemplatesPage),
            ("📖  Prompt库", PromptLibraryPage),
            ("🧠  Skill 工坊", SkillPage),
            ("✍  Prompt生成", GeneratorPage),
            ("🖼  图片反推", ImageAnalysisPage),
            ("🤖  模型中心", ModelsPage),
            ("📜  历史记录", HistoryPage),
            ("⚙  设置", SettingsPage),
        ]

        for title, page_cls in pages:
            self.navigation.addItem(QListWidgetItem(title))
            if page_cls is SettingsPage:
                page = page_cls(
                    config=self.config,
                    on_theme_changed=self._on_theme_changed,
                    task_manager=self.task_manager,
                )
            else:
                
                if page_cls is DashboardPage:
                    page = page_cls(service=self.dashboard_service, task_service=self.task_service,
                                    task_manager=self.task_manager, collector_service=self.collector_service)
                elif page_cls is CollectorPage:
                    page = page_cls(service=self.collector_service, task_manager=self.task_manager,
                                    model_service=self.model_service, knowledge_service=self.knowledge_service,
                                    config=self.config)
                elif page_cls is ImageAnalysisPage:
                    page = page_cls(image_service=self.image_service, knowledge_service=self.knowledge_service,
                                    model_service=self.model_service, task_manager=self.task_manager)
                elif page_cls is ModelsPage:
                    page = page_cls(model_service=self.model_service, task_manager=self.task_manager)
                elif page_cls is TemplatesPage:
                    page = page_cls(service=self.knowledge_service, pattern_service=self.pattern_service)
                elif page_cls is KnowledgePage:
                    page = page_cls(service=self.knowledge_service, generation_service=self.generation_service,
                                    task_manager=self.task_manager)
                elif page_cls is ComponentsPage:
                    page = page_cls(service=self.knowledge_service)
                elif page_cls is PromptLibraryPage:
                    page = page_cls(service=self.knowledge_service, knowledge_service=self.knowledge_service)
                elif page_cls is SkillPage:
                    page = page_cls(skill_service=self.skill_service, knowledge_service=self.knowledge_service,
                                    model_service=self.model_service, task_manager=self.task_manager,
                                    config=self.config, generation_service=self.generation_service)
                elif page_cls is GeneratorPage:
                    page = page_cls(generation_service=self.generation_service, pattern_service=self.pattern_service,
                                    task_manager=self.task_manager, knowledge_service=self.knowledge_service)
                else:
                    page = page_cls(db_path=self.db_path, task_manager=self.task_manager, collector_service=self.collector_service) if page_cls is HistoryPage else page_cls()
            self.stack.addWidget(page)

        self.navigation.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.navigation.setCurrentRow(0)

        container = QWidget()
        container.setObjectName("pageHost")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)
        self.container = container
        self.apply_background()

    def apply_background(self):
        """背景图只设在最外层容器（pageHost）上：整张图连续铺满整个软件窗口，
        所有页面与控件透明浮在图上，不再每个页面各画一张。"""
        from PySide6.QtWidgets import QApplication
        from app.core.constants import ACCENT_COLORS
        from app.ui.theme import build_background_overlay

        image_path = (self.config.get("background_image") or "").strip()
        qapp = QApplication.instance()
        current = qapp.styleSheet() if qapp else ""
        base = current.split("/*PFBG*/")[0]
        if not (image_path and Path(image_path).exists()):
            if qapp:
                qapp.setStyleSheet(base)
            self.container.setStyleSheet("")
            for i in range(self.stack.count()):
                page = self.stack.widget(i)
                if page is not None:
                    page.setStyleSheet("")
            return
        prepared = self._prepare_background(image_path)
        if prepared:
            posix = Path(prepared).as_posix()
            self.container.setStyleSheet(
                "#pageHost { background-image: url(\"" + posix + "\");"
                "background-position: center; background-repeat: no-repeat; "
                "background-attachment: fixed; }"
            )
        else:
            self.container.setStyleSheet("")
        accent = self.config.get("accent_color", "blue")
        if accent == "custom":
            accent_color = self.config.get("custom_accent_color") or "#3B82F6"
        else:
            accent_color = ACCENT_COLORS.get(accent, ACCENT_COLORS["blue"])[1]
        mode = self.config.get("theme_mode", "system")
        if mode not in ("dark", "light"):
            mode = "light"
        if qapp:
            qapp.setStyleSheet(base + build_background_overlay(mode, accent_color))

    def _prepare_background(self, image_path):
        """按当前窗口尺寸 cover 裁剪铺满整页，并按遮罩浓度混合窗口底色。"""
        try:
            return self._prepare_background_inner(image_path)
        except Exception:
            return None

    def _prepare_background_inner(self, image_path):
        from PIL import Image
        source = Path(image_path)
        size = self.size()
        width = min(1920, max(1024, size.width()))
        height = min(1080, max(640, size.height()))
        dim = max(0, min(90, int(self.config.get("background_dim_value", 45))))
        cache_dir = self.db_path.parent.parent / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"bg_{width}x{height}_{dim}.jpg"
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            img = Image.open(source).convert("RGB")
            scale = max(width / img.width, height / img.height)
            nw, nh = max(width, round(img.width * scale)), max(height, round(img.height * scale))
            img = img.resize((nw, nh))
            left, top = (nw - width) // 2, (nh - height) // 2
            img = img.crop((left, top, left + width, top + height))
            if dim > 0:
                dark = self.config.get("theme_mode", "system") == "dark"
                overlay_color = (27, 28, 31) if dark else (243, 244, 246)
                from PIL import Image as _I
                overlay = _I.new("RGB", img.size, overlay_color)
                img = Image.blend(img, overlay, dim / 100.0)
            img.save(target, "JPEG", quality=88)
        return str(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (self.config.get("background_image") or "").strip():
            from PySide6.QtCore import QTimer
            if not hasattr(self, "_bg_timer"):
                self._bg_timer = QTimer(self)
                self._bg_timer.setSingleShot(True)
                self._bg_timer.timeout.connect(self.apply_background)
            self._bg_timer.start(500)

    def _on_theme_changed(self):
        self.apply_theme_callback()
