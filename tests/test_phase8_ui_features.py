import json
from pathlib import Path

import httpx

from app.core.config import Config
from app.database.migrations import migrate
from app.database.repositories.core import ImageRepository, SourceRepository
from app.services.collector_service import CollectorService
from app.services.generation_service import GenerationService
from app.services.image_analysis_service import ImageAnalysisService
from app.services.knowledge_service import KnowledgeService
from app.services.model_service import ModelService
from app.services.providers.ollama import OllamaProvider
from PIL import Image


def test_provider_vision_payload(tmp_path: Path):
    image = tmp_path / "pic.png"
    Image.new("RGB", (4, 4), (200, 10, 10)).save(image)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"response": "masterpiece, red square\nNegative prompt: blurry", "done": True})

    provider = OllamaProvider("http://test:11434", transport=httpx.MockTransport(handler))
    text = provider.vision("反推这张图", "llava:13b", image, system="你是反推专家")
    assert text.startswith("masterpiece")
    payload = captured["payload"]
    assert payload["model"] == "llava:13b" and payload["system"] == "你是反推专家"
    assert payload["images"] and isinstance(payload["images"][0], str)

    with_none = OllamaProvider("http://t", transport=httpx.MockTransport(handler))
    import pytest
    with pytest.raises(RuntimeError):
        with_none.vision("x", "", image)


def test_vision_analyze_uses_default_model(tmp_path: Path):
    db = tmp_path / "v.db"
    migrate(db)
    image = tmp_path / "pic.png"
    Image.new("RGB", (4, 4), (10, 200, 10)).save(image)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "a green square, minimal\nNegative prompt: noise", "done": True})

    model_service = ModelService(Config(tmp_path / "config.json"), db)
    model_service.set_default("vision", "llava:13b")
    model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(handler))

    service = ImageAnalysisService(db)
    outcome = service.vision_analyze(image, model_service)
    assert outcome["model"] == "llava:13b"
    assert "green square" in outcome["text"]

    saved = service.save_prompt_text(outcome["text"], title="AI反推测试")
    assert saved["status"] == "created"
    prompt = service.prompts.get(saved["prompt_id"])
    assert prompt["prompt_text"] == "a green square, minimal"
    assert prompt["negative_prompt"] == "noise"


def test_collector_history_preview(tmp_path: Path):
    db = tmp_path / "c.db"
    migrate(db)
    service = CollectorService(db, tmp_path / "data")
    result = service.collect_text("赛博朋克城市夜景的完整正文内容。", "夜景文章")
    assert result["status"] == "created"
    rows = service.recent_sources(10)
    assert rows and rows[0]["title"]
    data = service.load_source_content(rows[0]["id"])
    assert data["kind"] == "document"
    assert "赛博朋克" in data["content"]


def test_generate_stream_and_bilingual_save(tmp_path: Path):
    db = tmp_path / "g.db"
    migrate(db)
    from app.services.model_service import ModelService
    from app.services.pattern_service import PatternService
    from app.database.repositories.core import PromptRepository
    model_service = ModelService(Config(tmp_path / "config.json"), db)
    model_service.set_default("llm", "llama3:test")
    service = GenerationService(db, Config(tmp_path / "config.json"), model_service,
                                knowledge_service=KnowledgeService(db), pattern_service=PatternService(db))

    chunks = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body.get("stream") is True
        lines = [
            json.dumps({"response": "【英文】\nmasterpiece"}),
            json.dumps({"response": ", neon city\n"}),
            json.dumps({"response": "【中文】\n杰作，霓虹城市\nNegative prompt: blurry\n"}),
            json.dumps({"done": True}),
        ]
        text = "\n".join(lines).encode("utf-8")
        return httpx.Response(200, content=text, headers={"Content-Type": "application/x-ndjson"})

    service.model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(handler))
    result = service.generate("霓虹城市", on_chunk=lambda text, delta: chunks.append(text))
    assert len(chunks) >= 2 and chunks[-1].startswith("【英文】")
    parsed = GenerationService.parse_result(result["result"])
    assert parsed["en"] == "masterpiece, neon city"
    assert parsed["zh"] == "杰作，霓虹城市"
    assert parsed["negative"] == "blurry"

    saved = service.save_as_prompt(result["result"], title="双语测试")
    assert saved["status"] == "created"
    row = PromptRepository(db).get(saved["prompt_id"])
    analysis = json.loads(row["analysis_result"])
    assert analysis["translation_zh"] == "杰作，霓虹城市"


def test_image_metadata_with_vision_fallback_paths(tmp_path: Path):
    db = tmp_path / "m.db"
    migrate(db)
    service = ImageAnalysisService(db)
    import pytest
    with pytest.raises(RuntimeError) as exc_info:
        service.vision_analyze(tmp_path / "missing.png", None)
    assert "模型服务" in str(exc_info.value)
