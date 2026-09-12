import json
from pathlib import Path

import httpx
import pytest

from app.core.config import Config
from app.database.migrations import migrate
from app.database.repositories.core import DocumentRepository, KnowledgeRepository, PromptRepository
from app.services.generation_service import GenerationService
from app.services.knowledge_service import KnowledgeService
from app.services.model_service import ModelService
from app.services.pattern_service import PatternService
from app.services.providers.ollama import OllamaProvider


def make_service(tmp_path: Path, handler) -> GenerationService:
    db = tmp_path / "gen.db"
    migrate(db)
    config = Config(tmp_path / "config.json")
    model_service = ModelService(config, db)
    service = GenerationService(
        db, config, model_service,
        knowledge_service=KnowledgeService(db), pattern_service=PatternService(db),
    )
    service.model_service.provider = lambda: OllamaProvider("http://test:11434", transport=httpx.MockTransport(handler))
    return service


def ollama_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/generate":
        return httpx.Response(200, json={"response": "masterpiece, neon city\nNegative prompt: blurry, lowres\nSteps: 20, CFG: 7", "done": True})
    return httpx.Response(404)


def test_parse_result_splits_sections():
    parsed = GenerationService.parse_result("masterpiece, neon city\nNegative prompt: blurry, lowres\nSteps: 20, CFG: 7")
    assert parsed["positive"] == "masterpiece, neon city"
    assert parsed["en"] == "masterpiece, neon city"
    assert parsed["negative"] == "blurry, lowres"
    assert "Steps: 20" in parsed["params"]
    simple = GenerationService.parse_result("just a prompt")
    assert simple["positive"] == "just a prompt" and simple["negative"] == "" and simple["params"] == ""
    think = GenerationService.parse_result("<think>推理过程</think>masterpiece, city")
    assert think["positive"] == "masterpiece, city"


def test_parse_result_bilingual_markers():
    text = "【英文】\nmasterpiece, neon city, cinematic\n【中文】\n杰作，霓虹城市，电影感\nNegative prompt: blurry\nSteps: 20"
    parsed = GenerationService.parse_result(text)
    assert parsed["en"] == "masterpiece, neon city, cinematic"
    assert parsed["zh"] == "杰作，霓虹城市，电影感"
    assert parsed["negative"] == "blurry"
    assert parsed["params"] == "Steps: 20"


def test_fill_template():
    text = GenerationService.fill_template("{subject} at night, {style}", {"subject": "cat", "style": "cinematic"})
    assert text == "cat at night, cinematic"


def test_retrieve_context(tmp_path: Path):
    service = make_service(tmp_path, ollama_handler)
    KnowledgeRepository(service.db_path).create({"source_type": "manual", "title": "霓虹城市笔记", "content": "赛博朋克风格要点：高对比、雨夜、霓虹灯。"})
    DocumentRepository(service.db_path).create({"title": "赛博朋克资料", "content": "赛博朋克配色以青色与品红为主。"})
    PromptRepository(service.db_path).create({"title": "旧Prompt", "prompt_text": "赛博朋克少女，neon city lights"})
    context = service.retrieve_context("赛博朋克")
    kinds = {item["type"] for item in context}
    assert {"knowledge", "document", "prompt"} <= kinds
    assert service.retrieve_context("") == []


def test_generate_without_default_llm(tmp_path: Path):
    service = make_service(tmp_path, ollama_handler)
    with pytest.raises(RuntimeError) as exc_info:
        service.generate("赛博朋克")
    assert "默认 LLM" in str(exc_info.value)


def test_generate_saves_history_and_prompt(tmp_path: Path):
    service = make_service(tmp_path, ollama_handler)
    service.model_service.set_default("llm", "llama3:test")

    outcome = service.generate("赛博朋克城市夜景", use_context=False)
    assert outcome["result"].startswith("masterpiece")
    assert outcome["model"] == "llama3:test"
    history = service.list_history()
    assert len(history) == 1 and history[0]["user_input"] == "赛博朋克城市夜景"

    outcome2 = service.generate("赛博朋克城市夜景", use_context=True)
    assert outcome2["history_id"] is not None

    saved = service.save_as_prompt(outcome["result"], title="测试生成")
    assert saved["status"] == "created"
    prompt = PromptRepository(service.db_path).get(saved["prompt_id"])
    assert prompt["prompt_text"] == "masterpiece, neon city"
    assert prompt["negative_prompt"] == "blurry, lowres"
    duplicate = service.save_as_prompt(outcome["result"])
    assert duplicate["status"] == "duplicate"


def test_generate_with_template(tmp_path: Path):
    service = make_service(tmp_path, ollama_handler)
    service.model_service.set_default("llm", "llama3:test")
    captured = {}

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return ollama_handler(request)

    service.model_service.provider = lambda: OllamaProvider("http://test:11434", transport=httpx.MockTransport(capturing_handler))
    pattern_service = PatternService(service.db_path)
    template_id = pattern_service.create_template(
        {"name": "夜景模板", "template_content": "{subject} at night, cinematic"},
        [{"variable_name": "subject", "display_name": "主体"}],
    )
    outcome = service.generate("一个少女", template_id=template_id, variables={"subject": "wandering girl"})
    prompt = captured["payload"]["prompt"]
    assert "wandering girl at night, cinematic" in prompt
    assert "补充需求：一个少女" in prompt
    assert outcome["history_id"] is not None
