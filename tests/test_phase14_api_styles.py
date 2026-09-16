import json
from pathlib import Path

import httpx
import pytest

from app.core.config import Config
from app.database.migrations import migrate
from app.database.repositories.core import ModelRepository
from app.services.keyword_organize_service import KeywordOrganizeService
from app.services.model_service import ModelService
from app.services.providers.ollama import OllamaProvider
from app.services.providers.openai_compat import OpenAICompatProvider


def test_openai_compat_generate_and_stream():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        if body.get("stream"):
            lines = [
                'data: {"choices":[{"delta":{"content":"霓虹"}}]}',
                'data: {"choices":[{"delta":{"content":"城市"}}]}',
                "data: [DONE]",
            ]
            return httpx.Response(200, content="\n".join(lines).encode("utf-8"),
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "生成的提示词"}}]})

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test",
                                    transport=httpx.MockTransport(handler))
    out = provider.generate("写提示词", "deepseek-chat", system="你是专家")
    assert out == "生成的提示词"
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "你是专家"}

    chunks = []
    streamed = provider.generate_stream("写提示词", "deepseek-chat", on_chunk=lambda t, d: chunks.append(t))
    assert streamed == "霓虹城市" and chunks[-1] == "霓虹城市"


def test_openai_compat_vision_and_errors(tmp_path: Path):
    from PIL import Image
    image = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (10, 10, 10)).save(image)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured["body"] = body
        return httpx.Response(200, json={"choices": [{"message": {"content": "图中有一轮明月"}}]})

    provider = OpenAICompatProvider("https://api.openai.com/v1", "sk-x", transport=httpx.MockTransport(handler))
    text = provider.vision("描述图片", "gpt-4o", image)
    assert "明月" in text
    content = captured["body"]["messages"][-1]["content"]
    assert content[0]["type"] == "text" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def handler401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    bad = OpenAICompatProvider("https://api.openai.com/v1", "sk-bad", transport=httpx.MockTransport(handler401))
    with pytest.raises(RuntimeError) as exc_info:
        bad.generate("x", "gpt-4o")
    assert "API Key 无效" in str(exc_info.value)


def test_provider_for_routing(tmp_path: Path):
    db = tmp_path / "m.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    service = ModelService(config, db)
    repo = ModelRepository(db)
    repo.create({"name": "llama3:latest", "provider": "ollama", "model_type": "llm"})
    repo.create({"name": "deepseek-chat", "provider": "api:deepseek", "model_type": "llm"})
    assert isinstance(service.provider_for("llama3:latest"), OllamaProvider)
    assert isinstance(service.provider_for("deepseek-chat"), OpenAICompatProvider)
    assert isinstance(service.provider_for("unknown-model"), OllamaProvider)
    assert service.provider_for("deepseek-chat").base_url == config.get("api_base_url", "").rstrip("/")


def test_default_model_persists_and_restores(tmp_path: Path):
    db = tmp_path / "m2.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    service = ModelService(config, db)
    repo = ModelRepository(db)
    repo.create({"name": "deepseek-chat", "provider": "api:deepseek", "model_type": "llm"})
    service.set_default("llm", "deepseek-chat")
    assert config.get("default_llm") == "deepseek-chat"
    assert repo.list(1, 0, "name=?", ("deepseek-chat",))[0]["is_default"] == 1

    # 模拟 config 丢失（如换了配置文件），启动时从 models 表恢复
    config2 = Config(tmp_path / "config_new.json")
    service2 = ModelService(config2, db)
    assert not config2.get("default_llm")
    restored = service2.restore_defaults_from_db()
    assert restored.get("llm") == "deepseek-chat"
    assert config2.get("default_llm") == "deepseek-chat"


def test_detect_styles_parsing(tmp_path: Path):
    db = tmp_path / "s.db"
    migrate(db)
    from app.database.repositories.core import SourceRepository, DocumentRepository
    source_id = SourceRepository(db).create({"title": "风格混杂的文章", "source_type": "web", "status": "completed"})
    DocumentRepository(db).create({"source_id": source_id, "title": "风格混杂的文章",
                                   "content": "包含赛博朋克、国风水墨与写实摄影三种风格的提示词资料。"})

    styles_json = json.dumps([
        {"style": "赛博朋克", "prompt": "cyberpunk neon city, rain, 85mm"},
        {"style": "国风水墨", "prompt": "traditional Chinese ink wash, misty mountains"},
        {"style": "写实摄影", "prompt": "documentary photograph, 35mm, natural light"},
    ], ensure_ascii=False)

    class FakeModelService:
        def get_default(self, t):
            return "deepseek-chat"
        def provider_for(self, name):
            return OpenAICompatProvider("https://api.deepseek.com/v1", "sk",
                                        transport=httpx.MockTransport(
                                            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": styles_json}}]})))

    organizer = KeywordOrganizeService(db)
    outcome = organizer.detect_styles(source_id, FakeModelService())
    assert len(outcome["styles"]) == 3
    assert outcome["styles"][0]["style"] == "赛博朋克"
    assert len(outcome["styles"][2]["prompt"]) > 10

    # 非 JSON 输出 → 单一风格兜底
    class BadModelService(FakeModelService):
        def provider_for(self, name):
            return OpenAICompatProvider("https://x/v1", "sk",
                                        transport=httpx.MockTransport(
                                            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "就一种综合风格，直接给提示词。"}}]})))
    fallback = KeywordOrganizeService(db).detect_styles(source_id, BadModelService())
    assert fallback["fallback"] is True and fallback["styles"][0]["style"] == "综合风格"


def test_memory_release_and_nav_helpers():
    from app.services.memory_service import release_memory, working_set_mb
    before = working_set_mb()
    assert before >= 0
    outcome = release_memory()
    assert set(outcome) == {"before_mb", "after_mb", "freed_mb"}
    assert outcome["freed_mb"] >= 0

    from app.ui.model_center_nav import is_model_missing
    from app.services.generation_service import MODEL_HINT
    assert is_model_missing(MODEL_HINT) is True
    assert is_model_missing("普通错误") is False


def test_api_profiles_save_apply_delete(tmp_path: Path):
    db = tmp_path / "prof.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    service = ModelService(config, db)

    service.save_api_profile("DeepSeek-主力", "deepseek", "https://api.deepseek.com/v1", "sk-deep-1234567890")
    service.save_api_profile("GLM-备用", "glm", "https://open.bigmodel.cn/api/paas/v4", "sk-glm-abcdef")
    profiles = service.list_api_profiles()
    assert [p["name"] for p in profiles] == ["DeepSeek-主力", "GLM-备用"]
    assert config.get("api_active_profile") == "GLM-备用"

    service.apply_api_profile("DeepSeek-主力")
    assert config.get("api_base_url") == "https://api.deepseek.com/v1"
    assert config.get("api_key") == "sk-deep-1234567890"
    assert config.get("api_active_profile") == "DeepSeek-主力"

    # 删除当前启用配置：密钥一并清空（防他人套用）
    outcome = service.delete_api_profile("DeepSeek-主力")
    assert outcome["cleared_active"] is True and outcome["remaining"] == 1
    assert config.get("api_key") == "" and config.get("api_base_url") == ""
    assert [p["name"] for p in service.list_api_profiles()] == ["GLM-备用"]

    # 删除非启用配置：不影响当前凭据
    service.apply_api_profile("GLM-备用")
    service.delete_api_profile("GLM-备用")
    assert service.list_api_profiles() == []

    import pytest
    with pytest.raises(ValueError):
        service.delete_api_profile("不存在")


def test_delete_provider_purges_backend_records(tmp_path: Path):
    """删除供应商：连后台模型记录一起清除，并重置失效默认模型。"""
    db = tmp_path / "purge.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    service = ModelService(config, db)
    repo = ModelRepository(db)

    service.save_api_profile("DeepSeek-主力", "deepseek", "https://api.deepseek.com/v1", "sk-deep-1234567890")
    service.apply_api_profile("DeepSeek-主力")
    repo.create({"name": "deepseek-chat", "provider": "api:deepseek", "model_type": "llm",
                 "endpoint": "https://api.deepseek.com/v1", "status": "available"})
    repo.create({"name": "llama3:latest", "provider": "ollama", "model_type": "llm"})
    service.set_default("llm", "deepseek-chat")
    assert config.get("default_llm") == "deepseek-chat"

    outcome = service.delete_api_profile("DeepSeek-主力")
    assert outcome["purged_models"] == 1
    assert outcome["cleared_active"] is True
    assert config.get("api_key") == ""
    # API 模型记录已清除，本地模型保留
    assert repo.list(1, 0, "name=?", ("deepseek-chat",)) == []
    assert repo.list(1, 0, "name=?", ("llama3:latest",))
    # 失效默认模型被重置
    assert config.get("default_llm") == ""
    assert outcome["cleared_defaults"].get("llm") == "deepseek-chat"
