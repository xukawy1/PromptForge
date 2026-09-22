from __future__ import annotations

import json

from app.core.config import Config
from app.database.repositories.core import ModelRepository
from app.services.providers.ollama import OllamaProvider
from app.services.providers.openai_compat import OpenAICompatProvider, VENDOR_PRESETS

VISION_KEYWORDS = ("llava", "bakllava", "moondream", "minicpm-v", "vision", "-vl", "vl-", "qwen2-vl",
                   "qwen2.5vl", "internvl", "pixtral", "step-1v",  # 常见 API 视觉模型
                   "-4v", "4v-", "gpt-4o", "gpt-4.1", "gemini", "claude-3", "claude-4", "omni")
EMBEDDING_KEYWORDS = ("embed", "bge", "e5", "gte", "nomic")


class ModelService:
    """模型中心服务：管理 Provider 连接、动态模型发现与默认模型设置。"""

    def __init__(self, config: Config, db_path):
        self.config = config
        self.db_path = db_path
        self.repo = ModelRepository(db_path)

    # ---------- Provider ----------

    def provider(self) -> OllamaProvider:
        """默认 Provider（ollama）；具体模型请用 provider_for 按型号路由。"""
        return OllamaProvider(self.config.get("ollama_endpoint", "http://127.0.0.1:11434"))

    # ---------- API 接入（OpenAI 兼容：GPT / DeepSeek / GLM / Kimi / 通义等） ----------

    def api_provider(self) -> OpenAICompatProvider:
        return OpenAICompatProvider(
            self.config.get("api_base_url", ""),
            self.config.get("api_key", ""),
        )

    def set_api_config(self, base_url: str, api_key: str):
        self.config.set("api_base_url", (base_url or "").strip())
        self.config.set("api_key", (api_key or "").strip())

    def test_api_connection(self) -> dict:
        models = self.api_provider().list_models()
        return {"base_url": self.config.get("api_base_url"), "model_count": len(models), "models": models}

    def refresh_api_models(self) -> dict:
        """把 API 模型清单同步到 models 表（provider 标记为 api:<vendor>）。"""
        vendor = self.config.get("api_vendor", "custom") or "custom"
        remote = self.api_provider().list_models()
        known = {row["name"]: row for row in self.repo.list(1000)}
        added, updated = 0, 0
        for item in remote:
            name = item.get("name") or ""
            if not name:
                continue
            model_type = self.classify_model(name)
            endpoint = self.config.get("api_base_url")
            if name in known:
                self.repo.update(known[name]["id"], {
                    "model_type": model_type, "endpoint": endpoint,
                    "status": "available", "provider": f"api:{vendor}",
                })
                updated += 1
            else:
                self.repo.create({
                    "name": name, "provider": f"api:{vendor}", "model_type": model_type,
                    "model_identifier": name, "endpoint": endpoint,
                    "status": "available",
                })
                added += 1
        return {"remote_count": len(remote), "added": added, "updated": updated}

    # ---------- API 配置多套保存 / 切换 / 删除 ----------

    def list_api_profiles(self) -> list:
        profiles = self.config.get("api_profiles") or []
        return [p for p in profiles if isinstance(p, dict) and p.get("name")]

    def _write_profiles(self, profiles):
        self.config.set("api_profiles", profiles)

    def save_api_profile(self, name: str, vendor: str = "", base_url: str = "", api_key: str = "") -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("请填写配置名称（如：DeepSeek-工作、GLM-备用）")
        profile = {"name": name, "vendor": vendor or "custom",
                   "base_url": (base_url or "").strip(), "api_key": (api_key or "").strip()}
        profiles = [p for p in self.list_api_profiles() if p.get("name") != name]
        profiles.append(profile)
        self._write_profiles(profiles)
        # 保存即启用：把该配置写进"当前凭据"。
        # 旧实现只写 api_active_profile 而不写 api_base_url/api_key，于是"添加供应商"后
        # 立刻刷新模型清单时用的还是空地址 → 弹"API 连接失败"；而紧接着点"测试所选"
        # 会先 apply 再测试 → 又提示成功（这个自相矛盾就是这么来的）。
        self.apply_api_profile(name)
        return profile

    def apply_api_profile(self, name: str) -> dict:
        profile = next((p for p in self.list_api_profiles() if p.get("name") == name), None)
        if not profile:
            raise ValueError(f"配置不存在：{name}")
        self.config.set("api_vendor", profile.get("vendor") or "custom")
        self.config.set("api_base_url", profile.get("base_url") or "")
        self.config.set("api_key", profile.get("api_key") or "")
        self.config.set("api_active_profile", profile["name"])
        return profile

    def delete_api_profile(self, name: str) -> dict:
        """删除供应商：移除配置与密钥，并清除后台同步的模型记录；
        若删除的是当前启用供应商，同时清空当前 API 凭据（防止他人套用）。"""
        profiles = self.list_api_profiles()
        profile = next((p for p in profiles if p.get("name") == name), None)
        if not profile:
            raise ValueError(f"供应商不存在：{name}")
        remaining = [p for p in profiles if p.get("name") != name]
        self._write_profiles(remaining)

        # 清除后台记录：该供应商地址同步过的模型行（provider=api:* 且 endpoint 匹配）
        purged = 0
        base_url = (profile.get("base_url") or "").strip()
        for row in self.repo.list(1000):
            provider_tag = str(row.get("provider") or "")
            endpoint = str(row.get("endpoint") or "")
            if provider_tag.startswith("api:") and base_url and endpoint == base_url:
                self.repo.delete(row["id"])
                purged += 1

        was_active = self.config.get("api_active_profile") == name or (
            bool(base_url) and self.config.get("api_base_url") == base_url)
        cleared_defaults = {}
        if was_active:
            self.config.set("api_active_profile", "")
            self.config.set("api_base_url", "")
            self.config.set("api_key", "")
            self.config.set("api_vendor", "custom")
        # 被清除的模型若仍被设为默认，一并清掉默认设置，避免残留失效模型
        for model_type, key in self.DEFAULT_KEYS.items():
            current = self.config.get(key) or ""
            if current and not self.repo.list(1, 0, "name=?", (current,)):
                self.config.set(key, "")
                cleared_defaults[model_type] = current
        return {"deleted": name, "cleared_active": bool(was_active),
                "purged_models": purged, "remaining": len(remaining),
                "cleared_defaults": cleared_defaults}

    def provider_for(self, model_name: str = ""):
        """按模型所属 Provider 路由：ollama 或 api:<vendor>；未知按 ollama 处理（保持兼容）。"""
        name = (model_name or "").strip()
        if name:
            rows = self.repo.list(1, 0, "name=?", (name,))
            if rows:
                provider_tag = str(rows[0].get("provider") or "ollama")
                if provider_tag.startswith("api:"):
                    return self.api_provider()
        return self.provider()

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
        # 同时在 models 表标记默认，作为 config 丢失时的恢复来源（只动同类型的行，避免清掉 vision/embedding 的标记）
        try:
            for row in self.repo.list(1000):
                if row["model_type"] != model_type:
                    continue
                is_default = 1 if row["name"] == name else 0
                if int(row.get("is_default") or 0) != is_default:
                    self.repo.update(row["id"], {"is_default": is_default})
        except Exception:
            pass

    def restore_defaults_from_db(self):
        """启动时：config 缺失的默认模型从 models 表 is_default 标记恢复。"""
        restored = {}
        for model_type, key in self.DEFAULT_KEYS.items():
            if self.config.get(key):
                continue
            rows = self.repo.list(1, 0, "is_default=1 AND model_type=?", (model_type,))
            if rows:
                self.config.set(key, rows[0]["name"])
                restored[model_type] = rows[0]["name"]
        return restored

    def get_default(self, model_type: str) -> str:
        key = self.DEFAULT_KEYS.get(model_type)
        return (self.config.get(key) or "") if key else ""

    def defaults(self) -> dict:
        return {model_type: self.get_default(model_type) for model_type in self.DEFAULT_KEYS}
