import json
from pathlib import Path

import httpx

from app.database.migrations import migrate
from app.database.repositories.core import CategoryRepository, KnowledgeRepository, SourceRepository, DocumentRepository
from app.services.keyword_organize_service import KeywordOrganizeService
from app.services.providers.openai_compat import OpenAICompatProvider


EXTRACT_JSON = json.dumps({
    "summary": {"title": "综合总结", "category": "风格", "prompt": "masterpiece, neon city, cinematic, ultra detailed"},
    "items": [
        {"title": "银发少女", "category": "人物", "prompt": "1girl, silver hair, white dress, portrait"},
        {"title": "雨夜街头", "category": "场景", "prompt": "rainy neon street at night, reflections"},
        {"title": "电影感光线", "category": "光线", "prompt": "cinematic lighting, dramatic shadows"},
    ],
}, ensure_ascii=False)


class FakeModelService:
    def __init__(self, payload):
        self._payload = payload

    def get_default(self, t):
        return "deepseek-chat"

    def provider_for(self, name):
        payload = self._payload
        return OpenAICompatProvider(
            "https://api.deepseek.com/v1", "sk",
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})))


def make_source(db):
    source_id = SourceRepository(db).create({"title": "微信文章", "url": "https://mp.weixin.qq.com/s/demo", "source_type": "web", "status": "completed"})
    DocumentRepository(db).create({"source_id": source_id, "title": "微信文章",
                                   "content": "文章包含一个综合提示词和多个角色提示词。"})
    return source_id


def test_extract_prompts_parsing(tmp_path: Path):
    db = tmp_path / "x.db"
    migrate(db)
    source_id = make_source(db)
    organizer = KeywordOrganizeService(db)
    outcome = organizer.extract_prompts(source_id, FakeModelService(EXTRACT_JSON))
    assert outcome["fallback"] is False
    assert outcome["summary"]["title"] == "综合总结"
    assert len(outcome["items"]) == 3
    assert outcome["items"][0]["category"] == "人物"
    # 非法分类被归一为“其他”
    bad = json.dumps({"summary": {"title": "S", "category": "乱七八糟", "prompt": "x"},
                      "items": [{"title": "A", "category": "不存在", "prompt": "y"}]}, ensure_ascii=False)
    outcome2 = KeywordOrganizeService(db).extract_prompts(source_id, FakeModelService(bad))
    assert outcome2["summary"]["category"] == "其他"
    assert outcome2["items"][0]["category"] == "其他"


def test_extract_prompts_non_json_fallback(tmp_path: Path):
    db = tmp_path / "y.db"
    migrate(db)
    source_id = make_source(db)
    organizer = KeywordOrganizeService(db)
    outcome = organizer.extract_prompts(source_id, FakeModelService("这是一段普通文字，没有 JSON。"))
    assert outcome["fallback"] is True
    assert outcome["summary"]["prompt"]


def test_save_extracted_prompts_by_category_and_overwrite(tmp_path: Path):
    db = tmp_path / "z.db"
    migrate(db)
    from app.database.seed import seed_defaults
    seed_defaults(db)
    source_id = make_source(db)
    organizer = KeywordOrganizeService(db)
    kb = KnowledgeRepository(db)
    cat_repo = CategoryRepository(db)
    lookup = {c["name"]: c["id"] for c in cat_repo.list(500) if c["parent_id"] is None}

    entries = [
        {"title": "银发少女", "category": "人物", "prompt": "1girl, silver hair"},
        {"title": "雨夜街头", "category": "场景", "prompt": "rainy street"},
        {"title": "电影感光线", "category": "光线", "prompt": "cinematic lighting"},
    ]
    outcome = organizer.save_extracted_prompts(source_id, entries, lookup, overwrite=True)
    assert outcome["saved"] == 3 and outcome["overwritten"] == 0
    assert outcome["by_category"] == {"人物": 1, "场景": 1, "光线": 1}

    # 分类归档正确
    person_name = kb.list(1, 0, "title=?", ("银发少女",))[0]
    assert person_name["category_id"] == lookup["人物"]

    # 重复保存 → 覆盖旧记录，不产生重复
    again = organizer.save_extracted_prompts(source_id, entries, lookup, overwrite=True)
    assert again["saved"] == 3 and again["overwritten"] == 3
    assert kb.count("source_type=?", ("extracted_prompt",)) == 3


def test_expand_prompt(tmp_path: Path):
    db = tmp_path / "e.db"
    migrate(db)
    organizer = KeywordOrganizeService(db)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert "扩写" in body["messages"][-1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "expanded cinematic prompt"}}]})

    class MS:
        def get_default(self, t):
            return "deepseek-chat"
        def provider_for(self, name):
            return OpenAICompatProvider("https://x/v1", "sk", transport=httpx.MockTransport(handler))

    outcome = organizer.expand_prompt("1girl, silver hair", MS())
    assert outcome["text"] == "expanded cinematic prompt"


def test_save_overwrites_same_url_sources(tmp_path: Path):
    """同一 URL 二次采集产生新来源时，旧来源的抽取记录也会被覆盖清理。"""
    db = tmp_path / "u.db"
    migrate(db)
    from app.database.seed import seed_defaults
    seed_defaults(db)
    organizer = KeywordOrganizeService(db)
    kb = KnowledgeRepository(db)
    cat_repo = CategoryRepository(db)
    lookup = {c["name"]: c["id"] for c in cat_repo.list(500) if c["parent_id"] is None}

    first = make_source(db)
    organizer.save_extracted_prompts(first, [{"title": "旧条目", "category": "人物", "prompt": "old"}], lookup)
    assert kb.count("source_type=?", ("extracted_prompt",)) == 1

    # 同 URL 的新来源（模拟内容变动后重新采集）
    second = SourceRepository(db).create({"title": "微信文章（更新）", "url": "https://mp.weixin.qq.com/s/demo",
                                          "source_type": "web", "status": "completed"})
    outcome = organizer.save_extracted_prompts(second, [{"title": "新条目", "category": "人物", "prompt": "new"}], lookup)
    assert outcome["overwritten"] == 1
    rows = kb.list(10, 0, "source_type=?", ("extracted_prompt",))
    assert len(rows) == 1 and rows[0]["title"] == "新条目"


def test_find_source_by_url(tmp_path: Path):
    from app.services.collector_service import CollectorService
    db = tmp_path / "f.db"
    migrate(db)
    service = CollectorService(db, tmp_path / "data")
    SourceRepository(db).create({"title": "文章A", "url": "https://mp.weixin.qq.com/s/abc",
                                 "source_type": "web", "status": "completed"})
    row = service.find_source_by_url("https://mp.weixin.qq.com/s/abc")
    assert row and row["title"] == "文章A"
    assert service.find_source_by_url("https://mp.weixin.qq.com/s/not-exist") is None
    assert service.find_source_by_url("") is None


def test_parse_extraction_json_variants():
    p = KeywordOrganizeService._parse_extraction_json
    assert p('{"items": [{"title":"A","category":"人物","prompt":"p"}]}')["items"][0]["title"] == "A"
    fenced = p('```json\n{"items": [{"title":"B","category":"场景","prompt":"q"},]}\n```')
    assert fenced and fenced["items"][0]["title"] == "B"
    truncated = p('{"items": [{"title": "银发少女", "category": "人物", "prompt": "1girl silver hair"}],')
    assert truncated and truncated["items"][0]["prompt"] == "1girl silver hair"
    assert p("完全不是JSON的普通文字") is None


def test_split_into_chunks():
    svc = object.__new__(KeywordOrganizeService)
    text = "\n".join(f"第{i}行内容" for i in range(3000))
    chunks = svc._split_into_chunks(text, chunk_size=3000, max_chunks=6)
    assert 2 <= len(chunks) <= 6
    assert all(len(c) <= 3200 for c in chunks)


def test_extract_chunked_merges_and_deduplicates(tmp_path: Path):
    db = tmp_path / "chunk.db"
    migrate(db)
    source_id = SourceRepository(db).create({"title": "超长文章", "source_type": "web", "status": "completed"})
    long_text = "\n".join(f"第{i}节：某角色提示词内容。" for i in range(900))
    DocumentRepository(db).create({"source_id": source_id, "title": "超长文章", "content": long_text})

    calls = {"n": 0}

    class ChunkModelService:
        def get_default(self, t):
            return "deepseek-chat"

        def provider_for(self, name):
            def handler(request: httpx.Request) -> httpx.Response:
                calls["n"] += 1
                payload = json.dumps({
                    "summary": {"title": "综合总结", "category": "风格", "prompt": f"summary-{calls['n']}"},
                    "items": [{"title": f"角色{calls['n']}", "category": "人物", "prompt": f"prompt-{calls['n']}"},
                              {"title": "重复项", "category": "人物", "prompt": "same prompt"}],
                }, ensure_ascii=False)
                return httpx.Response(200, json={"choices": [{"message": {"content": payload}}]})
            return OpenAICompatProvider("https://x/v1", "sk", transport=httpx.MockTransport(handler))

    organizer = KeywordOrganizeService(db)
    outcome = organizer.extract_prompts_from_text(long_text, ChunkModelService(), include_images=False)
    assert calls["n"] >= 2, "长文应按段多次调用模型"
    titles = [i["title"] for i in outcome["items"]]
    assert any(t.startswith("角色") for t in titles)
    # 跨段重复项去重
    assert titles.count("重复项") == 1
    assert outcome["chunks"] >= 2
    assert calls["n"] >= outcome["chunks"], "分段数不超过模型调用次数（含综合总结调用）"
