from app.services.phase2_finalize_service import Phase2FinalizeService
from app.services.pattern_service import PatternService
from app.services.knowledge_service import KnowledgeService
from pathlib import Path
from PySide6.QtWidgets import QApplication

from app.core.constants import APP_NAME, APP_VERSION
from app.core.paths import AppPaths
from app.core.config import Config
from app.core.logger import setup_logger
from app.core.events import EventBus
from app.database.migrations import migrate
from app.database.seed import seed_defaults
from app.tasks.task_manager import TaskManager
from app.services.dashboard_service import DashboardService
from app.services.task_service import TaskService
from app.services.collector_service import CollectorService
from app.services.image_analysis_service import ImageAnalysisService
from app.services.model_service import ModelService
from app.services.generation_service import GenerationService
from app.services.skill_service import SkillService
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme


class Application:
    def __init__(self):
        self.paths = AppPaths()
        self.paths.ensure()

        self.config = Config(self.paths.data_root / "config.json")
        self.logger = setup_logger(self.paths.logs)

        db_path = self.paths.app_root / self.config.get(
            "database", "data/database/promptforge.db"
        )
        migrate(db_path)
        seed_defaults(db_path)
        self.db_path = db_path
        try:
            from app.services.seed_content_service import SeedContentService
            from app.services.skill_service import SkillService
            seeder = SeedContentService(db_path)
            seeder.import_builtin()
            seeder.import_components_templates()
            skills_dir = self.paths.data_root / "skills"
            if skills_dir.exists():
                seeder.install_skills_from_dir(skills_dir, SkillService(db_path))
        except Exception:
            self.logger.exception("内置提示词包/组件模板/Skill 导入失败（不影响启动）")
        self.knowledge_service = KnowledgeService(self.db_path)
        self.pattern_service = PatternService(getattr(self, 'db_path', getattr(self, 'database_path', 'PromptForgeData/promptforge.db')))
        self.phase2_finalize = Phase2FinalizeService(getattr(self, 'db_path', getattr(self, 'database_path', 'PromptForgeData/promptforge.db')))

        self.event_bus = EventBus()
        self.dashboard_service = DashboardService(self.db_path)
        self.task_service = TaskService(self.db_path)
        self.recovered_task_ids = self.task_service.recover_interrupted_tasks()
        self.task_manager = TaskManager(task_service=self.task_service)
        self.collector_service = CollectorService(self.db_path, self.paths.data_root)
        self.image_analysis_service = ImageAnalysisService(self.db_path)
        self.model_service = ModelService(self.config, self.db_path)
        self.model_service.restore_defaults_from_db()
        self.generation_service = GenerationService(
            self.db_path, self.config, self.model_service,
            knowledge_service=self.knowledge_service, pattern_service=self.pattern_service,
        )
        self.skill_service = SkillService(self.db_path)

        self.qt_app = QApplication.instance() or QApplication([])
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setApplicationVersion(APP_VERSION)

        self.window = MainWindow(
            config=self.config,
            apply_theme_callback=self.apply_theme,
            dashboard_service=self.dashboard_service,
            knowledge_service=self.knowledge_service,
            collector_service=self.collector_service,
            task_manager=self.task_manager,
            db_path=self.db_path,
            task_service=self.task_service,
            image_service=self.image_analysis_service,
            model_service=self.model_service,
            generation_service=self.generation_service,
            pattern_service=self.pattern_service,
            skill_service=self.skill_service,
        )
        self.apply_theme()

        self.logger.info("PromptForge %s 启动完成", APP_VERSION)

    def apply_theme(self):
        apply_theme(
            self.qt_app,
            self.config.get("theme_mode", "system"),
            self.config.get("accent_color", "blue"),
            self.config.get("custom_accent_color"),
        )
        self.window.apply_background()

    def run(self):
        self.window.show()
        code = self.qt_app.exec()
        self.task_manager.shutdown()
        return code
