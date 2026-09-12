import json
from pathlib import Path

import httpx

from app.core.config import Config
from app.database.migrations import migrate
from app.database.repositories.core import ImageRepository, KnowledgeRepository
from app.services.collector_service import CollectorService
from app.services.generation_service import GenerationService
from app.services.keyword_organize_service import KeywordOrganizeService
from app.services.model_service import ModelService
from app.services.providers.ollama import OllamaProvider
from app.services.seed_content_service import SeedContentService
from PIL import Image


def ocr_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/generate":
        return httpx.Response(200, json={"response": "照片说明：城市夜景广告牌；文字内容：NEON CITY", "done": True})
    return httpx.Response(404)


def test_web_summary_with_ocr_and_llm(tmp_path: Path):
    db = tmp_path / "web.db"
    migrate(db)
    collector = CollectorService(db, tmp_path / "data")
    image = tmp_path / "banner.png"
    Image.new("RGB", (6, 6), (30, 30, 30)).save(image)
    from app.database.repositories.core import SourceRepository, DocumentRepository
    source_id = SourceRepository(db).create({"title": "霓虹城市文章", "source_type": "web", "status": "completed"})
    DocumentRepository(db).create({"source_id": source_id, "title": "霓虹城市文章", "content": "文章正文：霓虹城市夜景描写。"})
    ImageRepository(db).create({"source_id": source_id, "file_path": str(image), "file_hash": "h1", "format": "png"})

    model_service = ModelService(Config(tmp_path / "config.json"), db)
    model_service.set_default("vision", "llava:13b")
    model_service.set_default("llm", "llama3:test")
    model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(ocr_handler))

    organizer = KeywordOrganizeService(db)
    outcome = organizer.summarize_web_source(source_id, model_service)
    assert outcome["ocr_parts"] and "NEON CITY" in outcome["ocr_parts"][0]
    assert "提示词" in outcome["summary"] or len(outcome["summary"]) > 10

    knowledge_id = organizer.save_summary_to_knowledge(source_id, outcome["summary"], title="网页归纳测试", category_id=None)
    row = KnowledgeRepository(db).get(knowledge_id)
    assert row["source_type"] == "collector_source" and row["source_id"] == source_id


def test_translate(tmp_path: Path):
    db = tmp_path / "t.db"
    migrate(db)
    model_service = ModelService(Config(tmp_path / "config.json"), db)
    model_service.set_default("llm", "llama3:test")
    service = GenerationService(db, Config(tmp_path / "config.json"), model_service)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "夜空中最亮的星", "done": True})

    service.model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(handler))
    assert service.translate("the brightest star in the night sky", "中文（简体）") == "夜空中最亮的星"
    import pytest
    with pytest.raises(ValueError):
        service.translate("  ")
    model_service.config.set("default_llm", "")
    service2 = GenerationService(db, model_service.config, model_service)
    with pytest.raises(RuntimeError):
        service2.translate("hello", "中文（简体）")


def test_builtin_components_templates_seed(tmp_path: Path):
    db = tmp_path / "seed.db"
    migrate(db)
    service = SeedContentService(db)
    outcome = service.import_components_templates()
    assert outcome["components"] >= 6 and outcome["templates"] >= 4
    again = service.import_components_templates()
    assert again["components"] == 0 and again["templates"] == 0
    from app.services.pattern_service import PatternService
    rows = PatternService(db).templates.list(50)
    names = {r["name"] for r in rows}
    assert "H3 视频分镜模板" in names
