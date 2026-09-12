import json
from pathlib import Path


class Config:
    DEFAULTS = {
        "theme_mode": "system",
        "accent_color": "blue",
        "database": "data/database/promptforge.db",
        "ollama_endpoint": "http://127.0.0.1:11434",
        "default_llm": "",
        "default_vision": "",
        "default_embedding": "",
    }

    def __init__(self, path: Path):
        self.path = path
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    self.data.update(saved)
            except Exception:
                # 配置损坏时保留默认值，不阻止程序启动
                pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
