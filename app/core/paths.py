import sys
from pathlib import Path


class AppPaths:
    def __init__(self):
        if getattr(sys, "frozen", False):
            # PyInstaller 打包后，数据目录跟随 exe 所在位置。
            self.app_root = Path(sys.executable).resolve().parent
        else:
            self.app_root = Path(__file__).resolve().parents[2]
        self.data_root = self.app_root / "data"
        self.database = self.data_root / "database"
        self.logs = self.data_root / "logs"
        self.cache = self.data_root / "cache"
        self.knowledge = self.data_root / "knowledge"
        self.history = self.data_root / "history"
        self.backups = self.data_root / "backups"
        self.imports = self.data_root / "imports"
        self.exports = self.data_root / "exports"
        self.models = self.app_root / "models"
        self.plugins = self.app_root / "plugins"
        self.prompts = self.app_root / "prompts"

    def ensure(self):
        for path in (
            self.data_root, self.database, self.logs, self.cache,
            self.knowledge, self.history, self.backups,
            self.imports, self.exports, self.models, self.plugins,
            self.prompts,
        ):
            path.mkdir(parents=True, exist_ok=True)
