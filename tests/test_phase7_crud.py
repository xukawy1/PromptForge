import json
from pathlib import Path

from app.database.migrations import migrate
from app.database.repositories.base import BaseRepository
from app.database.repositories.core import (
    ComponentRelationRepository, KnowledgeRepository, PromptRepository,
)
from app.services.knowledge_service import KnowledgeService


def make_db(tmp_path: Path):
    db = tmp_path / "p7.db"
    migrate(db)
    return db


def test_list_all_available_on_repositories(tmp_path: Path):
    db = make_db(tmp_path)
    KnowledgeRepository(db).create({"source_type": "manual", "title": "条目A", "content": "内容"})
    KnowledgeRepository(db).create({"source_type": "manual", "title": "条目B", "content": "内容"})
    rows = KnowledgeRepository(db).list_all()
    assert [r["title"] for r in rows] == ["条目A", "条目B"]


def test_knowledge_search_keyword_and_category(tmp_path: Path):
    db = make_db(tmp_path)
    repo = KnowledgeRepository(db)
    repo.create({"source_type": "manual", "title": "光影笔记", "content": "伦勃朗光。"})
    repo.create({"source_type": "manual", "title": "色彩笔记", "content": "互补色。"})
    rows = repo.search("光影")
    assert len(rows) == 1 and rows[0]["title"] == "光影笔记"
    assert repo.search("")[0]["title"] in ("光影笔记", "色彩笔记")
    # KnowledgePage 调用路径：list_knowledge 返回列表
    service = KnowledgeService(db)
    items = service.list_knowledge(None, "色彩")
    assert len(items) == 1 and items[0]["title"] == "色彩笔记"


def test_prompt_search_shapes(tmp_path: Path):
    db = make_db(tmp_path)
    repo = PromptRepository(db)
    repo.create({"title": "城市夜景", "prompt_text": "neon city at night"})
    repo.create({"title": "人像", "prompt_text": "portrait, soft light"})
    paged = repo.search("", page=1, page_size=1)
    assert paged["total"] == 2 and len(paged["items"]) == 1 and paged["page_size"] == 1
    hits = repo.search("夜景")
    assert hits["total"] == 1 and hits["items"][0]["title"] == "城市夜景"
    listed = repo.search_text("portrait")
    assert isinstance(listed, list) and listed[0]["title"] == "人像"


def test_component_relation_crud(tmp_path: Path):
    db = make_db(tmp_path)
    from app.database.repositories.core import ComponentRepository
    components = ComponentRepository(db)
    first = components.create({"canonical_name": "cinematic lighting"})
    second = components.create({"canonical_name": "warm tone"})
    repo = ComponentRelationRepository(db)
    rid = repo.create({"component_id": first, "related_component_id": second, "relation_type": "搭配", "weight": 1.0})
    assert repo.get(rid)["relation_type"] == "搭配"
    assert repo.list_all()[0]["weight"] == 1.0


def test_create_knowledge_defaults_source_type(tmp_path: Path):
    db = make_db(tmp_path)
    service = KnowledgeService(db)
    kid = service.create_knowledge({"title": "默认来源测试", "content": "正文"})
    row = service.knowledge.get(kid)
    assert row["source_type"] == "manual"
