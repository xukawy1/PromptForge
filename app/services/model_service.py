from __future__ import annotations

import json

from app.core.config import Config
from app.database.repositories.core import ModelRepository
from app.services.providers.ollama import OllamaProvider

VISION_KEYWORDS = ("llava", "bakllava", "moondream", "minicpm-v", "vision", "-vl", "vl-", "qwen2-vl", "qwen2.5vl", "internvl")
EMBEDDING_KEYWORDS = ("embed", "bge", "e5", "gte", "nomic")


class ModelService:
    """模型中心服务：管理 Provider 连接、动态模型发现与默认模型设置。"""

    def __init__(self, config: Config, db_path):
        self.config = config
        self.db_path = db_path
        self.repo = ModelRepository(db_path)

    # ---------- Provider ----------

    def provider(self) -> OllamaProvider:
        return OllamaProvider(self.config.get("ollama_endpoint", "http://127.0.0.1:11434"))

    def set_endpoint(self, endpoint: str):
        self.config.set("ollama_endpoint", (endpoint or "").strip())

    def test_connection(self) -> dict:
        models = self.provider().list_models()
        return {"endpoint": self.config.get("ollama_endpoint"), "model_count": len(models), "models": models}

    # ---------- 模型发现与归类 ----------

    @staticmethod
    def classify_model(name: str) -> str:
        value = (name or "").lower()
        if any(keyword in value for keyword in EMBEDDING_KEYWORDS):
            return "embedding"
        if any(keyword in value for keyword in VISION_KEYWORDS):
            return "vision"
        return "llm"

    def refresh_remote_models(self) -> dict:
        """从 Ollama 动态发现模型并同步到本地模型表，不写死任何模型清单。"""
        remote = self.provider().list_models()
        known = {row["name"]: row for row in self.repo.list(1000)}
        added, updated = 0, 0
        for item in remote:
            name = item.get("name") or ""
            if not name:
                continue
            model_type = self.classify_model(name)
            parameters = json.dumps({
                "size": item.get("size") or 0,
                "family": item.get("family") or "",
                "parameter_size": item.get("parameter_size") or "",
                "quantization": item.get("quantization") or "",
            }, ensure_ascii=False)
            if name in known:
                self.repo.update(known[name]["id"], {
                    "model_type": model_type, "endpoint": self.config.get("ollama_endpoint"),
                    "status": "available", "parameters": parameters,
                })
                updated += 1
            else:
                self.repo.create({
                    "name": name, "provider": "ollama", "model_type": model_type,
                    "model_identifier": name, "endpoint": self.config.get("ollama_endpoint"),
                    "status": "available", "parameters": parameters,
                })
                added += 1
        return {"remote_count": len(remote), "added": added, "updated": updated}

    def list_models(self, model_type=None):
        if model_type:
            return self.repo.list(1000, 0, "model_type=?", (model_type,))
        return self.repo.list(1000)

    # ---------- 默认模型 ----------

    DEFAULT_KEYS = {"llm": "default_llm", "vision": "default_vision", "embedding": "default_embedding"}

    def set_default(self, model_type: str, name: str):
        key = self.DEFAULT_KEYS.get(model_type)
        if not key:
            raise ValueError(f"不支持的模型类型：{model_type}")
        self.config.set(key, name)

    def get_default(self, model_type: str) -> str:
        key = self.DEFAULT_KEYS.get(model_type)
        return (self.config.get(key) or "") if key else ""

    def defaults(self) -> dict:
        return {model_type: self.get_default(model_type) for model_type in self.DEFAULT_KEYS}
