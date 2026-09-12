import json
from pathlib import Path

import httpx
import pytest

from app.core.config import Config
from app.database.migrations import migrate
from app.services.model_service import ModelService
from app.services.providers.ollama import OllamaProvider


def make_provider(handler) -> OllamaProvider:
    return OllamaProvider("http://test:11434", transport=httpx.MockTransport(handler))


def tags_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [
            {"name": "llama3:latest", "size": 4700000000, "details": {"family": "llama", "parameter_size": "8B", "quantization_level": "Q4_0"}},
            {"name": "nomic-embed-text:latest", "size": 270000000, "details": {"family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16"}},
            {"name": "llava:13b", "size": 8000000000, "details": {"family": "llama", "parameter_size": "13B", "quantization_level": "Q4_0"}},
        ]})
    return httpx.Response(404, json={"error": "not found"})


def test_list_models_and_classification():
    provider = make_provider(tags_handler)
    models = provider.list_models()
    assert [m["name"] for m in models] == ["llama3:latest", "nomic-embed-text:latest", "llava:13b"]
    service = ModelService(Config(Path("nonexistent-config.json")), ":memory:")
    assert service.classify_model("llama3:latest") == "llm"
    assert service.classify_model("nomic-embed-text:latest") == "embedding"
    assert service.classify_model("llava:13b") == "vision"
    assert service.classify_model("qwen2.5vl:7b") == "vision"


def test_generate_and_embeddings_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = json.loads(request.content.decode("utf-8"))
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "生成的提示词", "done": True})
        if request.url.path == "/api/embeddings":
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        return httpx.Response(404)

    provider = make_provider(handler)
    text = provider.generate("写一个赛博朋克提示词", "llama3:latest", system="你是提示词工程师", options={"temperature": 0.7})
    assert text == "生成的提示词"
    assert seen["/api/generate"] == {"model": "llama3:latest", "prompt": "写一个赛博朋克提示词",
                                     "stream": False, "system": "你是提示词工程师",
                                     "options": {"num_predict": 2048, "temperature": 0.7}}
    vector = provider.embeddings("赛博朋克", "nomic-embed-text:latest")
    assert vector == [0.1, 0.2, 0.3]
    with pytest.raises(RuntimeError):
        provider.generate("x", "")


def test_connection_error_message():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = make_provider(handler)
    with pytest.raises(RuntimeError) as exc_info:
        provider.list_models()
    assert "无法连接 Ollama 服务" in str(exc_info.value)


def test_model_service_refresh_and_defaults(tmp_path: Path):
    db = tmp_path / "models.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    service = ModelService(config, db)
    provider = make_provider(tags_handler)
    remote = provider.list_models()
    known = {row["name"]: row for row in service.repo.list(1000)}
    assert not known

    # 直接调用服务内部逻辑：替换 provider 为 mock
    service.provider = lambda: provider
    result = service.refresh_remote_models()
    assert result == {"remote_count": 3, "added": 3, "updated": 0}
    rows = service.list_models()
    assert len(rows) == 3
    types = {row["name"]: row["model_type"] for row in rows}
    assert types["llama3:latest"] == "llm"
    assert types["nomic-embed-text:latest"] == "embedding"
    assert types["llava:13b"] == "vision"

    again = service.refresh_remote_models()
    assert again["added"] == 0 and again["updated"] == 3

    service.set_endpoint("http://127.0.0.1:11434")
    assert config.get("ollama_endpoint") == "http://127.0.0.1:11434"
    service.set_default("llm", "llama3:latest")
    service.set_default("embedding", "nomic-embed-text:latest")
    assert service.get_default("llm") == "llama3:latest"
    assert service.defaults()["embedding"] == "nomic-embed-text:latest"
    with pytest.raises(ValueError):
        service.set_default("audio", "x")
