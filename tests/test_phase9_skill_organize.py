import json
from pathlib import Path

import httpx
import pytest

from app.core.config import Config
from app.database.migrations import migrate
from app.services.keyword_organize_service import KeywordOrganizeService
from app.services.model_service import ModelService
from app.services.skill_service import SkillService
from app.services.collector_service import CollectorService
from app.services.providers.ollama import OllamaProvider


def test_migration_creates_skills_table(tmp_path: Path):
    db = tmp_path / "s.db"
    migrate(db)
    service = SkillService(db)
    assert service.list_skills() == []


def test_skill_install_and_apply(tmp_path: Path):
    db = tmp_path / "s2.db"
    migrate(db)
    skill_dir = tmp_path / "H3视频提示词skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "# H3 视频提示词编写\n\n格式要求：先写 5 秒分段，再写 integrated_multimodal_description。", encoding="utf-8")
    (skill_dir / "补充.md").write_text("结尾附 overall_soundscape 声音描述。", encoding="utf-8")

    service = SkillService(db)
    outcome = service.install_from_path(skill_dir)
    assert outcome["status"] == "created" and outcome["keyword"] == "H3视频提示词skill"
    assert outcome["file_count"] == 2
    skill = service.get(outcome["skill_id"])
    assert "integrated_multimodal_description" in skill["content"]

    updated = service.install_from_path(skill_dir)
    assert updated["status"] == "updated" and updated["skill_id"] == outcome["skill_id"]

    model_service = ModelService(Config(tmp_path / "config.json"), db)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert "skill" in (body.get("system") or "").lower() or "H3" in (body.get("system") or "")
        return httpx.Response(200, json={"response": "5秒：镜头推进……", "done": True})

    model_service.set_default("llm", "llama3:test")
    model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(handler))
    skill_id = outcome["skill_id"]
    outcome = service.apply_skill(skill_id, "一个少女在霓虹城市中行走", model_service)
    assert outcome["mode"] == "llm" and "5秒" in outcome["text"]

    saved_prompt = service.save_result_as_prompt(outcome["text"], title="Skill测试")
    assert saved_prompt["status"] == "created"

    saved_knowledge = service.save_result_to_knowledge(outcome["text"], skill_id, title="Skill成品测试")
    assert saved_knowledge


def test_skill_rule_mode_without_llm(tmp_path: Path):
    db = tmp_path / "s3.db"
    migrate(db)
    skill_file = tmp_path / "构图指南.md"
    skill_file.write_text("三分法构图优先，主体置于交叉点。", encoding="utf-8")
    service = SkillService(db)
    outcome = service.install_from_path(skill_file)
    result = service.apply_skill(outcome["skill_id"], "城市夜景")
    assert result["mode"] == "rule" and "构图指南" in result["text"] or "三分法" in result["text"]


def test_keyword_extract_and_organize(tmp_path: Path):
    db = tmp_path / "k.db"
    migrate(db)
    collector = CollectorService(db, tmp_path / "data")
    result = collector.collect_text(
        "电影感的霓虹城市夜景，一位少女半身像，电影灯光 lighting，浅景深 close-up，"
        "冷暖色彩 color 对比，masterpiece 最佳画质 quality，构图 composition 采用三分法。",
        "霓虹夜景笔记",
    )
    organizer = KeywordOrganizeService(db)
    keywords = organizer.extract_keywords("cinematic lighting neon city masterpiece 少女在霓虹灯下行走，电影感构图")
    assert keywords and len(keywords) <= 12

    outcome = organizer.organize_source(result["source_id"])
    assert outcome["status"] == "created"
    assert outcome["keywords"]
    assert outcome["categories"]
    duplicate = organizer.organize_source(result["source_id"])
    assert duplicate["status"] == "duplicate"

    with pytest.raises(ValueError):
        organizer.organize_source(99999)


def test_category_matching_rules():
    text = "cinematic lighting, close-up shot, warm color palette, best quality"
    matched = KeywordOrganizeService.match_categories(text, [])
    assert {"光线", "镜头语言", "色彩"} <= set(matched) and len(matched) <= 4
    zh_matched = KeywordOrganizeService.match_categories("这个场景适合运镜和配乐", [])
    assert "镜头语言" in zh_matched or "声音" in zh_matched


def test_ai_enhanced_organize(tmp_path: Path):
    db = tmp_path / "k2.db"
    migrate(db)
    collector = CollectorService(db, tmp_path / "data2")
    result = collector.collect_text("一篇关于电影灯光与构图的长文。", "灯光文章")
    organizer = KeywordOrganizeService(db)
    model_service = ModelService(Config(tmp_path / "config.json"), db)
    model_service.set_default("llm", "llama3:test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "规整总结：电影灯光要点……", "done": True})

    model_service.provider = lambda: OllamaProvider("http://t", transport=httpx.MockTransport(handler))
    outcome = organizer.organize_source(result["source_id"], use_llm=True, model_service=model_service)
    assert outcome["status"] == "created"
    from app.database.repositories.core import KnowledgeRepository
    row = KnowledgeRepository(db).get(outcome["knowledge_id"])
    assert "AI 规整总结" in row["content"]


def test_seed_content_idempotent(tmp_path: Path):
    from app.services.seed_content_service import SeedContentService
    db = tmp_path / "seed.db"
    migrate(db)
    service = SeedContentService(db)
    first = service.import_builtin()
    assert first["knowledge_cards"] >= 10 and first["prompts"] >= 8
    second = service.import_builtin()
    assert second["knowledge_cards"] == 0 and second["prompts"] == 0
