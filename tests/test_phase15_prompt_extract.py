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


def test_generate_deliverable_retries_then_hints_model_switch():
    """统一质量层：空/退化输出 → 重试 → 仍失败给出换模型提示。"""
    from app.services.prompt_quality import generate_deliverable, looks_degenerate

    class DegenerateProvider:
        def __init__(self):
            self.calls = 0
            self.last_done_reason = ""

        def generate_stream(self, prompt, model, system=None, options=None, on_chunk=None):
            self.calls += 1
            text = "秘" * 200            # 退化乱码
            if on_chunk:
                on_chunk(text, text)
            return text

    provider = DegenerateProvider()
    out = generate_deliverable(provider, "写一段提示词", "test-model", attempts=2)
    assert out["failed"] is True and out["text"] == "" and provider.calls == 2
    assert "换用更稳的本地模型" in out["hint"] and "API" in out["hint"]
    assert looks_degenerate("秘" * 200) and not looks_degenerate("正常的一段提示词，包含主体与环境描写。" * 5)


def test_expand_prompt_reports_hint_when_model_keeps_failing(tmp_path: Path):
    """扩写路径：模型连续输出退化内容时，返回换模型提示而不是把乱码塞给用户。"""
    db = tmp_path / "e2.db"
    migrate(db)
    organizer = KeywordOrganizeService(db)

    class DegenerateProvider:
        last_done_reason = ""

        def generate(self, prompt, model, system=None, options=None):
            return "巴拉巴拉诊" * 60

    class MS:
        def get_default(self, t):
            return "broken-model"

        def provider_for(self, name):
            return DegenerateProvider()

    outcome = organizer.expand_prompt("1girl, silver hair", MS())
    assert outcome["text"] == ""
    assert "broken-model" in outcome["hint"] and "API" in outcome["hint"]


def test_generation_service_hints_on_failure(tmp_path: Path):
    """Prompt 生成：模型写不出可用内容时不写历史，并明确提示换模型/用 API。"""
    from app.services.generation_service import GenerationService
    from app.core.config import Config

    db = tmp_path / "g.db"
    migrate(db)
    config = Config(tmp_path / "config.json")

    class DegenerateProvider:
        last_done_reason = ""

        def generate(self, prompt, model, system=None, options=None):
            return ""

    class MS:
        def get_default(self, t):
            return "empty-model"

        def provider_for(self, name):
            return DegenerateProvider()

    service = GenerationService(db, config, MS())
    result = service.generate("赛博朋克城市夜景")
    assert result["result"] == ""
    assert "empty-model" in result["hint"]
    assert not service.history_repo.list(10)      # 失败不落历史


def _translate_service(tmp_path, provider, name="t.db"):
    from app.services.generation_service import GenerationService
    from app.core.config import Config

    db = tmp_path / name
    migrate(db)
    config = Config(tmp_path / (name + ".config.json"))

    class MS:
        def get_default(self, t):
            return "local-model"

        def provider_for(self, model):
            return provider

    return GenerationService(db, config, MS())


class _EchoProvider:
    """回显式翻译：返回固定译文，记录每次收到的 prompt。"""

    last_done_reason = ""

    def __init__(self, reply="译文内容"):
        self.reply = reply
        self.prompts = []

    def generate(self, prompt, model, system=None, options=None, **kw):
        self.prompts.append(prompt)
        return self.reply

    def generate_stream(self, prompt, model, system=None, options=None, on_chunk=None, **kw):
        text = self.generate(prompt, model, system=system, options=options)
        if on_chunk:
            on_chunk(text, text)
        return text


def test_translate_long_text_is_chunked_not_truncated(tmp_path: Path):
    """长文翻译：按段落切段逐段翻译，不再只翻前 6000 字。"""
    provider = _EchoProvider("段落译文")
    service = _translate_service(tmp_path, provider)
    long_text = "\n\n".join(f"第{i}段：" + "内容" * 400 for i in range(1, 6))   # 远超单段上限

    progress = []
    result = service.translate(long_text, "中文（简体）", progress_cb=lambda d, t: progress.append((d, t)))

    assert len(provider.prompts) >= 3                      # 确实分段了
    assert all(len(p) < 6000 for p in provider.prompts)     # 每段都在单次上限内
    assert result.count("段落译文") == len(provider.prompts)  # 每段译文都拼进结果
    assert progress and progress[-1][0] == progress[-1][1]  # 进度收尾到 100%


def test_translate_short_text_single_call(tmp_path: Path):
    provider = _EchoProvider("一句话译文")
    service = _translate_service(tmp_path, provider, name="s.db")
    assert service.translate("A short prompt", "中文（简体）") == "一句话译文"
    assert len(provider.prompts) == 1


def test_translate_retries_then_raises_hint(tmp_path: Path):
    """模型返回空 → 每段重试一次 → 全失败时抛出换模型提示（不再静默返回空白）。"""
    provider = _EchoProvider("")          # 永远返回空
    service = _translate_service(tmp_path, provider, name="e.db")
    import pytest
    with pytest.raises(RuntimeError) as err:
        service.translate("some text to translate", "中文（简体）")
    assert "local-model" in str(err.value) and "API" in str(err.value)
    assert len(provider.prompts) == 2     # 首次 + 重试


def test_translate_partial_failure_marks_missing_chunk(tmp_path: Path):
    """部分段落译不出时：保留已译内容，并标出缺失段落，而不是整篇空白。"""
    class FlakyProvider(_EchoProvider):
        def generate(self, prompt, model, system=None, options=None, **kw):
            self.prompts.append(prompt)
            return "" if "FAILDING" in prompt else "OK译文"

    provider = FlakyProvider()
    service = _translate_service(tmp_path, provider, name="p.db")
    # 三段都超过单段上限，确保被切成多段，中间一段必定失败
    text = "\n\n".join([("正常段落甲" * 400), ("FAILDING 坏段" + "坏" * 2800), ("正常段落乙" * 400)])
    result = service.translate(text, "中文（简体）")
    assert result.count("OK译文") >= 2                 # 正常段落照常译出
    assert "未译出" in result and "段" in result       # 缺失段落被标出
    assert "建议重试" in result                        # 末尾给出建议


def test_save_api_profile_applies_credentials(tmp_path: Path):
    """保存供应商必须同时写入当前凭据：否则紧接着刷新模型会因 base_url 为空而报"连接失败"，
    而随后点测试又成功（自相矛盾）。"""
    from app.services.model_service import ModelService
    from app.core.config import Config

    db = tmp_path / "api.db"
    migrate(db)
    config = Config(tmp_path / "api.config.json")
    service = ModelService(config, db)

    service.save_api_profile("DeepSeek-工作", "deepseek", "https://api.deepseek.com/v1", "sk-test-key")
    assert config.get("api_base_url") == "https://api.deepseek.com/v1"
    assert config.get("api_key") == "sk-test-key"
    assert config.get("api_vendor") == "deepseek"
    assert config.get("api_active_profile") == "DeepSeek-工作"

    # 再存第二个供应商并切回第一个，凭据应跟随
    service.save_api_profile("GLM-备用", "glm", "https://open.bigmodel.cn/api/paas/v4", "key2")
    assert config.get("api_base_url").endswith("v4")
    service.apply_api_profile("DeepSeek-工作")
    assert config.get("api_base_url") == "https://api.deepseek.com/v1"
