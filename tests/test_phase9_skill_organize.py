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


def test_skill_system_excerpt_prefers_skill_md():
    from app.services.skill_service import SkillService
    content = ("## 来源文件：references/big.md\n" + "X" * 9000
               + "\n\n---\n\n## 来源文件：SKILL.md\n核心规范：必须分段描写。")
    excerpt = SkillService._system_excerpt(content, limit=2000)
    assert "核心规范" in excerpt and len(excerpt) <= 2200


def test_apply_skill_empty_llm_falls_back_nonempty(tmp_path: Path):
    db = tmp_path / "sk_empty.db"
    migrate(db)
    skill_file = tmp_path / "构图.md"
    skill_file.write_text("规范：三分法构图优先。", encoding="utf-8")
    service = SkillService(db)
    outcome = service.install_from_path(skill_file)

    class EmptyModelService:
        def get_default(self, t):
            return "test-model"
        def provider_for(self, name):
            class P:
                def generate(self, *a, **k):
                    return ""
            return P()

    result = service.apply_skill(outcome["skill_id"], "城市夜景素材", EmptyModelService())
    assert result["mode"] == "rule_fallback"
    assert result["text"].strip()
    assert "城市夜景素材" in result["text"]


def test_material_index_and_content(tmp_path: Path):
    db = tmp_path / "idx.db"
    migrate(db)
    from app.database.seed import seed_defaults
    seed_defaults(db)
    from app.database.repositories.core import KnowledgeRepository, CategoryRepository
    kb = KnowledgeRepository(db)
    cat_id = CategoryRepository(db).list(1, 0, "name=?", ("人物",))[0]["id"]
    kid = kb.create({"source_type": "manual", "title": "银发少女素材", "content": "1girl, silver hair", "category_id": cat_id})

    service = SkillService(db)
    index = service.list_material_index(50)
    assert index and "content" not in index[0]
    assert index[0]["title"] == "银发少女素材"
    assert service.get_material_content(kid) == "1girl, silver hair"
    names = service.category_name_map()
    assert names.get(cat_id) == "人物"


def test_rename_skill_and_skip_reinstall(tmp_path: Path):
    db = tmp_path / "rn.db"
    migrate(db)
    skill_dir = tmp_path / "h3-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# H3 提示词编写\n规范内容。", encoding="utf-8")
    service = SkillService(db)
    outcome = service.install_from_path(skill_dir)
    sid = outcome["skill_id"]

    # 重命名成功并持久化
    renamed = service.rename_skill(sid, "H3视频提示词（我的命名）")
    assert renamed["keyword"] == "H3视频提示词（我的命名）"
    assert service.get(sid)["name"] == "H3视频提示词（我的命名）"

    import pytest
    # 造第二个 skill 验证重名冲突
    d2 = tmp_path / "mj-skill"; d2.mkdir()
    (d2 / "SKILL.md").write_text("# MJ\nMJ 规范。", encoding="utf-8")
    out2 = service.install_from_path(d2)
    with pytest.raises(ValueError):
        service.rename_skill(out2["skill_id"], "H3视频提示词（我的命名）")
    with pytest.raises(ValueError):
        service.rename_skill(sid, "   ")

    # 启动自动安装：重命名后不会重复装回原目录
    from app.services.seed_content_service import SeedContentService
    seeder = SeedContentService(db)
    installed = seeder.install_skills_from_dir(tmp_path, service)
    keywords = [s["keyword"] for s in service.list_skills()]
    assert "h3-skill" not in keywords, "已安装（含重命名）的来源不应被重复安装"
    assert "H3视频提示词（我的命名）" in keywords


def test_update_skill_content(tmp_path: Path):
    db = tmp_path / "upd.db"
    migrate(db)
    skill_file = tmp_path / "指南.md"
    skill_file.write_text("原始规范内容。", encoding="utf-8")
    service = SkillService(db)
    outcome = service.install_from_path(skill_file)
    sid = outcome["skill_id"]

    updated = service.update_skill(sid, content="修改后的规范：先写主体，再写光线。", description="改写版说明")
    assert updated["content"].startswith("修改后的规范")
    assert updated["description"] == "改写版说明"
    assert service.get(sid)["content"].startswith("修改后的规范")

    # 仅改说明时内容保持不变
    service.update_skill(sid, description="只改说明")
    row = service.get(sid)
    assert row["description"] == "只改说明"
    assert row["content"].startswith("修改后的规范")

    import pytest
    with pytest.raises(ValueError):
        service.update_skill(sid, content="   ")
    with pytest.raises(ValueError):
        service.update_skill(99999, content="x")
