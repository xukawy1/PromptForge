from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from app.database.repositories.core import SourceRepository, DocumentRepository, ImageRepository, KnowledgeRepository, CategoryRepository

STOPWORDS = set(
    "的 了 在 和 是 就 都 而 及 与 着 或 一个 没有 我们 你们 他们 它们 这 那 这个 那个 以及 可以 "
    "通过 进行 使用 效果 关于 相关 以下 如下 描述 要点 内容 文章 "
    "the a an and or of to in on for with is are was were be been this that these those it its as at by from".split()
)

# 关键词 → 知识分类映射（覆盖默认种子分类，中英均可命中）
CATEGORY_KEYWORDS = {
    "人物": ("character", "portrait", "girl", "boy", "woman", "man", "person", "figure", "人物", "角色", "少女", "少女像", "人像"),
    "场景": ("scene", "environment", "background", "city", "landscape", "场景", "环境", "背景", "城市", "夜景"),
    "摄影": ("photography", "photo", "camera", "shot", "摄影", "拍摄", "实拍", "写真"),
    "镜头语言": ("lens", "close-up", "closeup", "zoom", "pan", "angle", "wide shot", "景别", "特写", "运镜", "镜头", "焦段", "视角"),
    "光线": ("light", "lighting", "glow", "shadow", "sunlight", "neon", "光线", "光照", "光影", "霓虹", "逆光"),
    "构图": ("composition", "rule of thirds", "framing", "构图", "布局", "留白", "对称"),
    "色彩": ("color", "colour", "palette", "tone", "色调", "色彩", "配色", "色板"),
    "风格": ("style", "art", "anime", "cinematic", "realistic", "painting", "风格", "画风", "电影感", "写实", "动漫"),
    "视频": ("video", "motion", "camera movement", "时长", "视频", "运镜", "动态", "帧"),
    "声音": ("sound", "audio", "music", "voice", "声音", "音效", "配乐", "配音", "旁白"),
    "质量": ("quality", "masterpiece", "best quality", "8k", "4k", "hd", "高清", "质量", "画质", "杰作"),
}

MAX_KEYWORDS = 12


class KeywordOrganizeService:
    """采集内容智能规整：关键词提取 → 分类匹配 → 汇总为知识条目（可选大模型增强总结）。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self.sources = SourceRepository(db_path)
        self.documents = DocumentRepository(db_path)
        self.images = ImageRepository(db_path)
        self.knowledge = KnowledgeRepository(db_path)
        self.categories = CategoryRepository(db_path)

    # ---------- 关键词 ----------

    @staticmethod
    def extract_keywords(text, limit=MAX_KEYWORDS):
        """轻量关键词提取：英文按词、中文按 2-gram 滑窗统计词频，无需外部分词依赖。"""
        text = (text or "")[:20000]
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        english = [w.lower() for w in words if w.lower() not in STOPWORDS]
        chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        grams = []
        for run in chinese_runs:
            if run in STOPWORDS:
                continue
            for i in range(len(run) - 1):
                gram = run[i:i + 2]
                if gram not in STOPWORDS:
                    grams.append(gram)
        counter = Counter(english + grams)
        return [word for word, _count in counter.most_common(limit) if len(word) >= 2]

    @classmethod
    def match_categories(cls, text, keywords):
        """按关键词映射匹配知识分类名：中文子串匹配、英文整词匹配，返回命中的分类名。"""
        haystack = (text or "").lower()
        joined = " ".join(keywords).lower()
        matched = []
        for category, words in CATEGORY_KEYWORDS.items():
            if category in haystack:
                matched.append(category)
                continue
            for word in words:
                wl = word.lower()
                if re.search(r"[a-z]", wl):
                    if re.search(rf"\b{re.escape(wl)}\b", haystack) or re.search(rf"\b{re.escape(wl)}\b", joined):
                        matched.append(category)
                        break
                else:
                    if wl in haystack:
                        matched.append(category)
                        break
        return matched[:4]

    def _resolve_category_id(self, names):
        if not names:
            return None, []
        rows = {r["name"]: r["id"] for r in self.categories.list(500)}
        resolved = [(name, rows.get(name)) for name in names if rows.get(name)]
        if not resolved:
            return None, names
        return resolved[0][1], [name for name, _ in resolved]

    # ---------- 网页识别归纳 ----------

    def summarize_web_source(self, source_id, model_service=None, use_ocr=True):
        """网页来源 → 图片 OCR + 文字内容 → 归纳成普通格式提示词描述（可再编辑）。"""
        source = self.sources.get(source_id)
        if not source:
            raise ValueError("来源不存在")
        doc_rows = self.documents.list(1, 0, "source_id=?", (source_id,))
        content = (doc_rows[0].get("content") if doc_rows else "") or source.get("description") or ""
        title = (doc_rows[0].get("title") if doc_rows else "") or source.get("title") or ""

        ocr_parts, ocr_model = [], ""
        if use_ocr and model_service is not None:
            model = model_service.get_default("vision") or model_service.get_default("llm") or ""
            if model:
                ocr_model = model
                provider = model_service.provider_for(model)
                for img in self.images.list(3, 0, "source_id=?", (source_id,)):
                    path = img.get("file_path") or ""
                    if not path or not Path(path).exists():
                        continue
                    try:
                        raw = provider.vision(
                            "请提取这张图片中的全部文字内容，并用一句话说明图片展示了什么。"
                            "只输出：图片说明 + 文字内容。",
                            model, path,
                        )
                        from app.services.generation_service import clean_llm_text
                        text = clean_llm_text(raw)
                        if text:
                            ocr_parts.append(f"[图片·{Path(path).name}] {text[:500]}")
                    except Exception as exc:
                        ocr_parts.append(f"[图片识别失败] {exc}")

        combined = content[:6000] + ("\n\n" + "\n".join(ocr_parts) if ocr_parts else "")
        llm_summary, llm_model = "", ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
            if llm_model:
                provider = model_service.provider_for(llm_model)
                raw = provider.generate(
                    "请把下面的网页资料归纳总结成一段\"普通格式提示词\"：用自然语言完整描述可直接用于 AI 绘画/视频的画面，"
                    "涵盖主体、环境、光线、构图、色彩、氛围与质量要素，中文输出，300 字以内，直接给描述本身。\n\n"
                    + combined[:6000],
                    llm_model,
                )
                from app.services.generation_service import clean_llm_text
                llm_summary = clean_llm_text(raw)

        if not llm_summary:
            keywords = self.extract_keywords(content)
            categories = self.match_categories(content, keywords)
            llm_summary = (
                f"{title}\n关键词索引：{', '.join(keywords) or '无'}\n"
                f"自动分类：{' / '.join(categories) or '未匹配'}\n\n"
                f"正文要点：\n{content[:1200]}"
            )

        return {
            "summary": llm_summary,
            "ocr_parts": ocr_parts,
            "ocr_model": ocr_model,
            "llm_model": llm_model,
            "title": title,
        }

    def save_summary_to_knowledge(self, source_id, summary, title="", category_id=None):
        content = (summary or "").strip()
        if not content:
            raise ValueError("归纳内容为空")
        return self.knowledge.create({
            "source_type": "collector_source", "source_id": source_id,
            "title": (title or "网页归纳").strip()[:120],
            "content": content,
            "summary": "网页采集识别归纳",
            "category_id": category_id,
            "knowledge_type": "prompt_material",
            "confidence": 1.0,
        })


    # ---------- 多风格识别（网页/资料中含多种提示词风格时） ----------

    STYLE_PROMPT = (
        "你是提示词风格分析专家。阅读下面的资料，识别其中体现出的不同提示词风格（如写实摄影、电影感、"
        "赛博朋克、国风水墨、日系插画、3D 渲染、极简平面、复古胶片等），最多输出 6 种最有代表性的。\n"
        "为每一种风格写一段可直接复制使用的完整英文提示词（结合资料内容，覆盖主体/环境/光线/构图/色彩/风格/质量）。\n"
        "严格只输出 JSON 数组，不要任何多余文字，格式：\n"
        '[{"style": "风格名(中文)", "prompt": "English prompt ..."}]'
    )

    def detect_styles(self, source_id, model_service, use_ocr=True, max_styles=6):
        """识别资料中的多种提示词风格，返回 [{style, prompt}]（不入库，供用户选择后保存）。"""
        material = self.collect_source_material(source_id, use_ocr=use_ocr, model_service=model_service)
        combined = material["content"]
        if material["ocr_parts"]:
            combined += "\n\n" + "\n".join(material["ocr_parts"])
        if not combined.strip():
            raise ValueError("该来源没有可分析的内容")
        llm_model = ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
        if not llm_model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        provider = model_service.provider_for(llm_model)
        raw = provider.generate(self.STYLE_PROMPT + "\n\n资料：\n" + combined[:6000], llm_model)
        from app.services.generation_service import clean_llm_text
        text = clean_llm_text(raw)
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return {"styles": [{"style": "综合风格", "prompt": text}], "model": llm_model, "fallback": True}
        import json as _json
        try:
            items = _json.loads(text[start:end + 1])
        except ValueError:
            return {"styles": [{"style": "综合风格", "prompt": text}], "model": llm_model, "fallback": True}
        styles = []
        for item in items[:max_styles]:
            if not isinstance(item, dict):
                continue
            style = str(item.get("style") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if prompt:
                styles.append({"style": style or f"风格{len(styles) + 1}", "prompt": prompt})
        if not styles:
            return {"styles": [{"style": "综合风格", "prompt": text}], "model": llm_model, "fallback": True}
        return {"styles": styles, "model": llm_model, "fallback": False}

    # ---------- 提示词拆分抽取（综合总结 + 多个分散提示词） ----------

    PROMPT_CATEGORIES = ("人物", "场景", "摄影", "镜头语言", "光线", "构图", "色彩", "风格", "视频", "声音", "质量", "其他")

    EXTRACT_PROMPT = (
        "你是提示词整理专家。阅读下面的资料（可能是网页文章，常包含 1 段综合提示词和多个分散的人物/场景提示词），"
        "把所有独立可用的提示词全部找出来，并额外生成一个综合总结提示词。\n"
        "严格只输出 JSON，不要任何多余文字，格式：\n"
        '{"summary": {"title": "综合总结", "category": "风格", "prompt": "English prompt"}, '
        '"items": [{"title": "中文短关键词(4-12字)", "category": "人物", "prompt": "English prompt"}]}\n'
        "要求：\n"
        f"1. category 必须从以下列表选择：{'/'.join(PROMPT_CATEGORIES)}；\n"
        "2. title 用 4-12 个中文字概括该提示词主体（如「银发少女」「雨夜街头」「电影感光线」）；\n"
        "3. prompt 保留原文的完整英文提示词（不要省略、不要翻译丢失信息）；\n"
        "4. summary.prompt 把全文要点合成一段完整可用的提示词；\n"
        "5. 【重要】逐一提取资料中出现的每一个独立提示词，宁多勿少、绝不合并：例如文章里有 8 个不同人物的提示词，"
        "就必须输出 8 条 items（每条一个人物，各自用该人物的特征做 title）；场景/道具等其他独立提示词同样各自成条；\n"
        "6. items 不要包含 summary 的重复内容，summary 只放综合汇总那一条。"
    )

    def extract_prompts(self, source_id, model_service, use_ocr=True):
        """把来源内容拆分为「综合总结提示词 + 多个分散提示词」，返回 {"summary": {...}, "items": [...]}（不入库）。"""
        material = self.collect_source_material(source_id, use_ocr=use_ocr, model_service=model_service)
        combined = material["content"]
        if material["ocr_parts"]:
            combined += "\n\n" + "\n".join(material["ocr_parts"])
        if not combined.strip():
            raise ValueError("该来源没有可分析的内容")
        llm_model = ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
        if not llm_model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        provider = model_service.provider_for(llm_model)
        raw = provider.generate(self.EXTRACT_PROMPT + "\n\n资料：\n" + combined[:8000], llm_model)
        from app.services.generation_service import clean_llm_text
        text = clean_llm_text(raw)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            import json as _json
            try:
                data = _json.loads(text[start:end + 1])
            except ValueError:
                data = None
            if isinstance(data, dict):
                return self._normalize_extraction(data, llm_model)
        # 兜底：无法解析时用关键词骨架作为单一综合提示
        fallback = self.build_prompt_card(source_id, use_llm=True, model_service=model_service, use_ocr=use_ocr)
        return {
            "summary": {"title": "综合总结", "category": "风格", "prompt": fallback.get("text") or ""},
            "items": [],
            "model": llm_model,
            "fallback": True,
        }

    def _normalize_extraction(self, data, llm_model):
        def norm_category(value):
            value = str(value or "").strip()
            return value if value in self.PROMPT_CATEGORIES else "其他"

        def norm_item(item, default_title):
            if not isinstance(item, dict):
                return None
            prompt = str(item.get("prompt") or "").strip()
            if not prompt:
                return None
            title = str(item.get("title") or "").strip()[:40] or default_title
            return {"title": title, "category": norm_category(item.get("category")), "prompt": prompt}

        summary_raw = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        summary = norm_item(summary_raw, "综合总结")
        items = []
        for raw_item in (data.get("items") or [])[:40]:
            entry = norm_item(raw_item, f"提示词{len(items) + 1}")
            if entry:
                items.append(entry)
        if summary:
            summary["category"] = norm_category(summary.get("category")) if summary.get("category") else "风格"
            summary["title"] = summary.get("title") or "综合总结"
        return {"summary": summary, "items": items, "model": llm_model, "fallback": False}

    def expand_prompt(self, text, model_service, instruction=None):
        """按需调用大模型，把一条提示词扩写规整为完整成品。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("没有可扩写的内容")
        llm_model = ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
        if not llm_model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        provider = model_service.provider_for(llm_model)
        task = instruction or (
            "把下面的提示词扩写规整成一条完整、可直接使用的成品提示词：补全主体特征、环境、光线、构图、色彩、风格与质量要素，"
            "保持原有意图与风格；只输出扩写后的提示词正文（英文），不要解释。"
        )
        raw = provider.generate(task + "\n\n原提示词：\n" + text[:4000], llm_model)
        from app.services.generation_service import clean_llm_text
        return {"text": clean_llm_text(raw), "model": llm_model}

    def _related_source_ids(self, source_id):
        """同来源 + 同 URL 的全部来源 ID（重复导入时用于覆盖旧记录）。"""
        source = self.sources.get(source_id)
        ids = [source_id]
        url = (source or {}).get("url")
        if url:
            for row in self.sources.list(100, 0, "url=?", (url,)):
                if row["id"] not in ids:
                    ids.append(row["id"])
        return ids

    def save_extracted_prompts(self, source_id, entries, category_id_by_name, overwrite=True):
        """按类别归档保存抽取的提示词；重复导入时覆盖同一来源/URL 的旧记录。"""
        entries = [e for e in (entries or []) if (e.get("prompt") or "").strip()]
        if not entries:
            raise ValueError("没有可保存的提示词")
        overwritten = 0
        if overwrite:
            for sid in self._related_source_ids(source_id):
                for row in self.knowledge.list(200, 0, "source_id=? AND source_type IN ('extracted_prompt','multi_style')", (sid,)):
                    self.knowledge.delete(row["id"])
                    overwritten += 1
        saved, saved_by_category = 0, {}
        for entry in entries:
            category = entry.get("category") if entry.get("category") in self.PROMPT_CATEGORIES else "其他"
            category_id = category_id_by_name.get(category) or category_id_by_name.get("其他")
            self.knowledge.create({
                "source_type": "extracted_prompt", "source_id": source_id,
                "title": str(entry.get("title") or "提示词")[:120],
                "content": entry.get("prompt") or "",
                "summary": f"关键词：提示词拆分 | 分类：{category}",
                "category_id": category_id,
                "knowledge_type": "prompt",
                "confidence": 1.0,
            })
            saved += 1
            saved_by_category[category] = saved_by_category.get(category, 0) + 1
        return {"saved": saved, "overwritten": overwritten, "by_category": saved_by_category}

    # ---------- 提示词卡规整（预览用，不入库） ----------

    def collect_source_material(self, source_id, use_ocr=True, model_service=None, ocr_limit=3):
        """来源 → 正文 + 图片 OCR 文字的合并素材。"""
        source = self.sources.get(source_id)
        if not source:
            raise ValueError("来源不存在")
        doc_rows = self.documents.list(1, 0, "source_id=?", (source_id,))
        content = (doc_rows[0].get("content") if doc_rows else "") or source.get("description") or ""
        title = (doc_rows[0].get("title") if doc_rows else "") or source.get("title") or ""
        ocr_parts = []
        if use_ocr and model_service is not None:
            model = model_service.get_default("vision") or model_service.get_default("llm") or ""
            if model:
                provider = model_service.provider_for(model)
                for img in self.images.list(ocr_limit, 0, "source_id=?", (source_id,)):
                    path = img.get("file_path") or ""
                    if not path or not Path(path).exists():
                        continue
                    try:
                        raw = provider.vision(
                            "请提取这张图片中的全部文字内容，并用一句话说明图片展示了什么。只输出：图片说明 + 文字内容。",
                            model, path,
                        )
                        from app.services.generation_service import clean_llm_text
                        text = clean_llm_text(raw)
                        if text:
                            ocr_parts.append(f"[图片·{Path(path).name}] {text[:500]}")
                    except Exception as exc:
                        ocr_parts.append(f"[图片识别失败] {exc}")
        return {"title": title, "content": content[:6000], "ocr_parts": ocr_parts}

    def build_prompt_card(self, source_id, use_llm=False, model_service=None, use_ocr=True):
        """把采集内容规整为可直接用于 AI 图片/视频生成的提示词卡（只保留画面要素，不入库）。"""
        material = self.collect_source_material(source_id, use_ocr=use_ocr, model_service=model_service)
        keywords = self.extract_keywords(material["content"])
        combined = material["content"] + ("\n\n" + "\n".join(material["ocr_parts"]) if material["ocr_parts"] else "")
        if use_llm and model_service is not None:
            llm_model = model_service.get_default("llm") or ""
            if llm_model:
                provider = model_service.provider_for(llm_model)
                raw = provider.generate(
                    "你是提示词规整专家。把下面的资料提炼成可直接用于 AI 图片/视频生成的提示词卡。\n"
                    "严格输出以下格式：\n"
                    "【English】一行英文正向提示词（逗号分隔，覆盖主体、环境、光线、构图、色彩、风格、质量）\n"
                    "【中文】英文提示词的中文翻译\n"
                    "Negative prompt: 一行负向提示词\n"
                    "建议参数: 若干行（尺寸/时长/镜头/步数等）\n"
                    "要求：只保留与画面相关的要素，剔除广告、导航、版权声明等与画面无关的内容。\n\n资料：\n" + combined[:6000],
                    llm_model,
                )
                from app.services.generation_service import clean_llm_text
                card = clean_llm_text(raw)
                if card:
                    return {"text": card, "keywords": keywords, "mode": "llm", "model": llm_model}
        keywords_line = ", ".join(keywords) or "无"
        categories = self.match_categories(material["content"], keywords)
        card = (
            "【English 提示词骨架】{subject}, {environment}, {lighting}, {composition}, {style}, ultra detailed\n"
            "【画面要素（由资料提炼）】\n"
            f"- 关键词索引：{keywords_line}\n"
            f"- 自动分类：{' / '.join(categories) or '未匹配'}\n"
            f"- 素材要点：{material['content'][:600]}\n"
            + ("\n【图片识别内容】\n" + "\n".join(material["ocr_parts"]) + "\n" if material["ocr_parts"] else "")
            + "\n（未连接大模型：以上为基础骨架，可在模型中心设置默认 LLM 后重新规整为完整提示词）"
        )
        return {"text": card, "keywords": keywords, "mode": "keyword", "model": ""}

    # ---------- 规整 ----------

    def organize_source(self, source_id, use_llm=False, model_service=None):
        """把采集来源规整为知识条目，返回创建结果。"""
        source = self.sources.get(source_id)
        if not source:
            raise ValueError("来源不存在")
        existing = self.knowledge.list(1, 0, "source_type='collector_source' AND source_id=?", (source_id,))
        if existing:
            return {"status": "duplicate", "knowledge_id": existing[0]["id"], "message": "该来源已规整过知识库"}

        doc_rows = self.documents.list(1, 0, "source_id=?", (source_id,))
        if doc_rows:
            content = doc_rows[0].get("content") or ""
            title = doc_rows[0].get("title") or source.get("title") or ""
        else:
            img_rows = self.images.list(1, 0, "source_id=?", (source_id,))
            if not img_rows:
                raise ValueError("该来源没有可规整的正文或图片")
            content = json.dumps({"file_path": img_rows[0].get("file_path"), "metadata": img_rows[0].get("metadata")},
                                 ensure_ascii=False)
            title = source.get("title") or "图片来源"

        keywords = self.extract_keywords(content)
        category_names = self.match_categories(content, keywords)
        category_id, resolved_names = self._resolve_category_id(category_names)

        from app.services.prompt_structure_service import PromptStructureService
        structure = PromptStructureService().build_structure(content)
        slot_items = {s["name_zh"]: s["items"] for s in structure.get("slots", []) if s.get("items")}

        sections = [f"【规整摘要】{title}", f"【关键词索引】{', '.join(keywords) or '无'}"]
        if resolved_names:
            sections.append(f"【自动分类】{' / '.join(resolved_names)}")
        if slot_items:
            sections.append("【提示词要素】")
            for name, items in slot_items.items():
                sections.append(f"- {name}：{', '.join(items)}")
        sections.append(f"【原始正文】\n{content[:6000]}")

        llm_note = ""
        if use_llm and model_service is not None:
            model_name = model_service.get_default("llm") or ""
            if model_name:
                provider = model_service.provider_for(model_name)
                summary = provider.generate(
                    "请把下面的资料整理成便于撰写 AI 提示词的知识卡片：一行规整总结，随后列出 5-10 个最有用的提示词关键词，"
                    "不要输出无关解释。\n\n" + content[:4000],
                    model_name,
                )
                from app.services.generation_service import clean_llm_text
                summary = clean_llm_text(summary)
                sections.insert(1, f"【AI 规整总结（{model_name}）】\n{summary[:1500]}")
                llm_note = f"AI 规整（{model_name}）"
            else:
                llm_note = "未设置默认 LLM，已用关键词规整"
        elif use_llm:
            llm_note = "未设置默认 LLM，已用关键词规整"

        knowledge_id = self.knowledge.create({
            "source_type": "collector_source", "source_id": source_id,
            "title": (title or "采集规整")[:120],
            "content": "\n".join(sections),
            "summary": "关键词：" + (", ".join(keywords[:8]) or "无") + (f"；{llm_note}" if llm_note else ""),
            "category_id": category_id,
            "knowledge_type": "prompt_material",
            "confidence": 1.0,
        })
        return {
            "status": "created", "knowledge_id": knowledge_id,
            "keywords": keywords, "categories": resolved_names,
            "message": "已规整同步到知识库" + (f"（{llm_note}）" if llm_note else "（关键词规整）"),
        }
