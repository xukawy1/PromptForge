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
                images = [img for img in self.images.list(3, 0, "source_id=?", (source_id,))
                          if (img.get("file_path") or "") and Path(img["file_path"]).exists()]
                if images:
                    from app.services.providers.ollama import OllamaProvider
                    if isinstance(provider, OllamaProvider):
                        # 本地视觉模型：串行，避免并发把显存与请求队列挤爆
                        results = [self._ocr_one_image(provider, model, img) for img in images]
                    else:
                        # API 视觉模型：并发调用，分析耗时取决于最慢的那张图
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=min(3, len(images))) as pool:
                            results = list(pool.map(lambda img: self._ocr_one_image(provider, model, img), images))
                    ocr_parts.extend(r for r in results if r)

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
                    llm_model, think=False,
                )
                from app.services.generation_service import clean_llm_text
                from app.services.prompt_quality import clean_deliverable
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
        raw = provider.generate(self.STYLE_PROMPT + "\n\n资料：\n" + combined[:6000], llm_model, think=False)
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
        "5. 【重要】逐一提取资料中出现的每一个独立提示词，宁多勿少、绝不合并：例如资料里有八仙的提示词，"
        "就必须输出 8 条 items，title 分别是「铁拐李」「汉钟离」「张果老」「吕洞宾」「何仙姑」「蓝采和」「韩湘子」「曹国舅」，"
        "每条的 prompt 是该角色对应的完整提示词；\n"
        "6. 先读取资料结构：如果资料按序号（1. / 2. / ①② / 一、二、）或关键字标题（如「关键词：xxx」、小节标题）"
        "列出多个提示词，就按每个序号/标题逐条拆分，序号或标题词直接用于 title；\n"
        "7. 如果资料中含图片识别文字（以 [图片·文件名] 开头），每一张图片都必须单独输出一条 item："
        "title 用图片内容的关键词命名（如「图1 银发少女」），category 按图片内容判断（人物图→「人物」、场景图→「场景」），"
        "prompt 依据图片描述文字写成完整提示词；有几张图片就至少有几条图片条目，不同图片绝不合并；\n"
        "8. items 不要包含 summary 的重复内容，summary 只放综合汇总那一条；\n"
        "9. 即使资料排版混乱、没有明确序号，也要按语义把每一段独立的提示词拆出来，不允许因为「格式不标准」就返回空数组。"
    )

    CHUNK_PROMPT = (
        "你是提示词提取器。下面的文字是资料的第 {index}/{total} 段。"
        "请提取本段中出现的所有独立提示词（人物/场景/道具等各自成条，不允许合并），"
        "严格只输出 JSON 数组：\n"
        '[{"title": "中文短关键词", "category": "人物", "prompt": "English prompt"}]\n'
        f"category 可选值：{'/'.join(PROMPT_CATEGORIES)}；本段没有提示词时输出 []。"
    )

    RETRY_PROMPT = (
        "上一次整理失败了。请只做一件事：把下面资料中出现的提示词逐条列出来，"
        "每条输出一行 JSON（一行一个对象，不要包在数组里，不要输出其他文字）：\n"
        '{"title": "中文短关键词", "category": "人物", "prompt": "完整英文提示词"}\n'
        f"category 可选值：{'/'.join(PROMPT_CATEGORIES)}。"
    )


    def extract_prompts(self, source_id, model_service, use_ocr=True, progress_cb=None):
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
        full_prompt = self.EXTRACT_PROMPT + "\n\n资料：\n" + combined[:8000]
        if progress_cb and hasattr(provider, "generate_stream"):
            def _on_chunk(text, _delta):
                progress_cb(len(text))
            raw = provider.generate_stream(full_prompt, llm_model, on_chunk=_on_chunk, think=False)
        else:
            raw = provider.generate(full_prompt, llm_model, think=False)
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

    # ---------- 解析辅助 ----------

    @staticmethod
    def _parse_extraction_json(cleaned: str):
        """多策略解析模型输出：标准 JSON → 修复尾部逗号/代码块 → 逐对象正则扫描。"""
        import json as _json
        import re as _re
        if not cleaned:
            return None
        candidates = []
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            candidates.append(cleaned[start:end + 1])
        text = cleaned.replace("```json", "").replace("```", "")
        s2, e2 = text.find("{"), text.rfind("}")
        if s2 >= 0 and e2 > s2:
            candidates.append(text[s2:e2 + 1])
        for candidate in candidates:
            try:
                data = _json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except ValueError:
                repaired = _re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    data = _json.loads(repaired)
                    if isinstance(data, dict):
                        return data
                except ValueError:
                    pass
        # 最后兜底：逐条扫描 {"title": "...", "category": "...", "prompt": "..."} 形态的对象
        items = []
        for match in _re.finditer(r"\{[^{}]*?\"prompt\"\s*:\s*\"((?:[^\"\\]|\\.)*)\"[^{}]*?\}", cleaned, _re.S):
            block = match.group(0)

            def field(name, default=""):
                m = _re.search(r"\"" + name + r"\"\s*:\s*\"((?:[^\"\\]|\\.)*)\"", block, _re.S)
                if not m:
                    return default
                try:
                    return _json.loads("\"" + m.group(1) + "\"")
                except ValueError:
                    return m.group(1)

            prompt = field("prompt")
            if prompt.strip():
                items.append({"title": field("title"), "category": field("category"), "prompt": prompt})
        if items:
            return {"items": items}
        return None

    def ocr_source_images(self, source_id, model_service, limit=3, progress_cb=None):
        """对来源图片做 OCR（用于把图片内容并入提示词拆分）。"""
        parts = []
        if model_service is None:
            return parts
        model = model_service.get_default("vision") or model_service.get_default("llm") or ""
        if not model:
            return parts
        provider = model_service.provider_for(model)
        images = [img for img in self.images.list(limit, 0, "source_id=?", (source_id,))
                  if (img.get("file_path") or "") and Path(img["file_path"]).exists()]
        if not images:
            return parts
        prompt = "请提取这张图片中的全部文字，并用一两句话说明图片展示的内容（人物/场景/风格）。只输出内容本身。"

        def _one(img):
            path = img["file_path"]
            try:
                from app.services.generation_service import clean_llm_text
                raw = provider.vision(prompt, model, path, think=False)
                text = clean_llm_text(raw)
                return f"[图片·{Path(path).name}] {text[:400]}" if text else ""
            except Exception:
                return ""

        from app.services.providers.ollama import OllamaProvider
        if isinstance(provider, OllamaProvider):
            # 本地视觉模型：串行（并发只会排队，还可能把显存挤爆）
            for i, img in enumerate(images):
                parts.append(_one(img))
                if progress_cb:
                    progress_cb(i + 1, len(images))
        else:
            # API 视觉模型：并发（多张图的总耗时接近最慢的那一张）
            from concurrent.futures import ThreadPoolExecutor, as_completed
            ordered = [""] * len(images)
            with ThreadPoolExecutor(max_workers=min(4, len(images))) as pool:
                futures = {pool.submit(_one, img): idx for idx, img in enumerate(images)}
                done = 0
                for fut in as_completed(futures):
                    ordered[futures[fut]] = fut.result()
                    done += 1
                    if progress_cb:
                        progress_cb(done, len(images))
            parts.extend(r for r in ordered if r)
        return [p for p in parts if p]

    def _split_into_chunks(self, text, chunk_size=3200, max_chunks=6):
        """按行/段落把长文切成若干段（每段不超过 chunk_size 字符）。"""
        lines = (text or "").splitlines()
        chunks, current = [], []
        size = 0
        for line in lines:
            line_len = len(line) + 1
            if current and size + line_len > chunk_size:
                chunks.append("\n".join(current))
                current, size = [], 0
                if len(chunks) >= max_chunks:
                    break
            current.append(line)
            size += line_len
        if current and len(chunks) < max_chunks:
            chunks.append("\n".join(current))
        return chunks or [text[:chunk_size]]

    # ---------- 文本拆分 ----------

    def _collect_chunk_items(self, provider, llm_model, prompt_text, progress_cb=None, progress_base=None, progress_span=None):
        """跑一次分段提取：优先 JSON 对象响应，失败则按 JSON 数组重试。返回 items 列表。"""
        from app.services.generation_service import clean_llm_text

        def _run(user_prompt, stream=True):
            if stream and progress_cb and hasattr(provider, "generate_stream"):
                def _on_chunk(partial, _delta):
                    if progress_cb and progress_base is not None:
                        progress_cb(min(progress_base + (progress_span or 0), progress_base + len(partial) / 40.0))
                return provider.generate_stream(user_prompt, llm_model, on_chunk=_on_chunk, think=False)
            return provider.generate(user_prompt, llm_model, options={"num_predict": 2048}, think=False)

        cleaned = clean_llm_text(_run(prompt_text))
        data = self._parse_extraction_json(cleaned)
        items = []
        if isinstance(data, dict):
            items = self._normalize_extraction(data, llm_model).get("items") or []
        elif isinstance(data, list):
            for raw in data:
                entry = self._normalize_extraction({"items": [raw]}, llm_model).get("items") or []
                items.extend(entry)
        if items:
            return items
        # 单段重试：换成"每行一个 JSON"的提取提示词
        retry_cleaned = clean_llm_text(_run(self.RETRY_PROMPT + "\n\n资料：\n" + prompt_text.split("资料：")[-1][:6000], stream=False))
        for line in retry_cleaned.splitlines():
            line = line.strip().strip(",")
            if not line.startswith("{"):
                continue
            parsed = self._parse_extraction_json(line)
            if isinstance(parsed, dict):
                cand = parsed if "prompt" in parsed else (parsed.get("items") or [None])[0]
                if isinstance(cand, dict):
                    entry = self._normalize_extraction({"items": [cand]}, llm_model).get("items") or []
                    items.extend(entry)
        return items

    def _image_item_title(self, ocr_text, index, model_service=None):
        """从图片 OCR 文本中提取一个短标题（关键字命名）。"""
        import re as _re
        text = (ocr_text or "").strip()
        # 去掉 [图片·xxx] 前缀
        text = _re.sub(r"^\[图片·[^\]]*\]\s*", "", text)
        # 取第一句话，截取前 10 个有效字符
        first = _re.split(r"[。！？!?\n，,；;]", text)[0].strip()
        keyword = first[:10] if first else ""
        return f"图片{index}：{keyword}" if keyword else f"图片{index}"

    def _image_prompt_text(self, ocr_text):
        """把图片 OCR 描述整理为一条可用的提示词文本。"""
        import re as _re
        text = _re.sub(r"^\[图片·[^\]]*\]\s*", "", (ocr_text or "").strip())
        return text.strip()

    def extract_prompts_from_text(self, text, model_service, progress_cb=None,
                                  source_id=None, include_images=True):
        """提示词拆分：图片逐张 OCR 成条 + 长文多线程分段分析 + 合并去重 + 失败重试，
        保证只要原文里有提示词就一定返回清单。"""
        import concurrent.futures as _futures
        text = (text or "").strip()
        if not text:
            raise ValueError("没有可分析的文字，请先在左侧填入或保留原文内容")
        llm_model = ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
        if not llm_model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        provider = model_service.provider_for(llm_model)

        # 1) 图片逐张 OCR（如有图片）——每张图片保证单独成条
        image_parts, ocr_model = [], ""
        if include_images and source_id is not None:
            ocr_model = (model_service.get_default("vision") or model_service.get_default("llm") or "") if model_service else ""
            image_parts = self.ocr_source_images(source_id, model_service, limit=6,
                                                 progress_cb=lambda i, n: progress_cb(i * 3.0) if progress_cb else None)
            if progress_cb:
                progress_cb(10.0)

        # 2) 长文分段
        chunks = self._split_into_chunks(text, chunk_size=3200, max_chunks=8)

        # 3) 多线程逐段分析（API 模型 3 线程 / 本地模型 2 线程），实时汇总
        from app.services.providers.openai_compat import OpenAICompatProvider
        workers = 3 if isinstance(provider, OpenAICompatProvider) else 2
        workers = max(1, min(workers, len(chunks)))
        all_items, summaries = [], []
        completed = {"n": 0}
        total = len(chunks)

        def _work(idx_chunk):
            idx, chunk = idx_chunk
            base = 12.0 + (idx / max(1, total)) * 78.0
            span = 78.0 / max(1, total)
            prompt_text = (
                (self.EXTRACT_PROMPT if total == 1
                 else self.CHUNK_PROMPT.replace("{index}", str(idx + 1)).replace("{total}", str(total)))
                + "\n\n资料：\n" + chunk
            )
            try:
                items = self._collect_chunk_items(provider, llm_model, prompt_text,
                                                  progress_cb=progress_cb, progress_base=base, progress_span=span)
            except Exception:
                items = []
            # 单段仍为空：整段作为一条兜底提示词（保证不丢内容）
            if not items:
                title = f"段落{idx + 1}"
                fallback_text = chunk.strip()[:1200]
                if fallback_text:
                    items = [{"title": title, "category": "其他", "prompt": fallback_text}]
            if total == 1:
                from app.services.generation_service import clean_llm_text
                # 单段模式顺带取 summary（对象响应时）
                pass
            completed["n"] += 1
            if progress_cb:
                progress_cb(min(92.0, 12.0 + completed["n"] / total * 78.0))
            return idx, items

        if total > 1 and workers > 1:
            with _futures.ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(_work, list(enumerate(chunks))))
        else:
            results = [_work(pair) for pair in enumerate(chunks)]
        results.sort(key=lambda r: r[0])
        for _idx, items in results:
            all_items.extend(items)

        # 4) 综合总结（用首个分段的提取做 summary，失败则拼接）
        if progress_cb:
            progress_cb(94.0)
        try:
            summary_raw = provider.generate(
                self.EXTRACT_PROMPT.split("严格只输出 JSON")[0]
                + "只输出一条综合提示词（英文），不要 JSON、不要解释。\n\n资料：\n" + text[:3000],
                llm_model, options={"num_predict": 512}, think=False)
            from app.services.generation_service import clean_llm_text
            from app.services.prompt_quality import clean_deliverable
            summaries.append(clean_deliverable(clean_llm_text(summary_raw)))
        except Exception:
            pass

        # 5) 图片条目并入（每张图片一条，缺则补）
        existing_blob = "\n".join((it.get("prompt") or "") for it in all_items)
        for i, part in enumerate(image_parts, 1):
            image_text = self._image_prompt_text(part)
            if not image_text:
                continue
            # 若模型已为该图片产出条目（图片描述关键词出现），不重复添加
            keyword = image_text[:12]
            if keyword and keyword in existing_blob:
                continue
            title = self._image_item_title(part, i)
            category = (self.match_categories(image_text, self.extract_keywords(image_text)) or ["场景"])[0]
            all_items.append({"title": title, "category": category, "prompt": image_text})

        # 6) 合并去重
        merged, seen = [], set()
        for item in all_items:
            key = (item.get("title") or "") + "|" + (item.get("prompt") or "")[:60]
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        summary_text = "\n\n".join(s for s in summaries if s)[:2000]
        if progress_cb:
            progress_cb(97.0)
        return {
            "summary": {"title": "综合总结", "category": "风格", "prompt": summary_text},
            "items": merged,
            "model": llm_model,
            "chunks": total,
            "ocr_images": len(image_parts),
            "ocr_model": ocr_model,
            "fallback": not merged,
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

    def expand_prompt(self, text, model_service, instruction=None, progress_cb=None):
        """按需调用大模型，把一条提示词扩写规整为完整成品（产出成品，不搬运规范原文）。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("没有可扩写的内容")
        llm_model = ""
        if model_service is not None:
            llm_model = model_service.get_default("llm") or ""
        if not llm_model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        from app.services.prompt_quality import DELIVERABLE_RULES, generate_deliverable
        provider = model_service.provider_for(llm_model)
        task = instruction or (
            "把下面的提示词素材扩写规整成一条完整、可直接使用的成品提示词："
            "补全主体特征、环境、光线、构图、色彩、风格与质量要素，保持原有意图与风格，正文用英文。"
        )
        prompt = (
            f"{DELIVERABLE_RULES}\n\n=== 本次任务 ===\n{task}\n\n=== 提示词素材 ===\n{text[:4000]}"
        )
        retry = (
            f"{DELIVERABLE_RULES}\n\n=== 本次任务 ===\n{task}\n\n"
            f"只输出成品提示词正文（英文），写满再停，不要输出任何规范或说明。\n\n"
            f"=== 提示词素材 ===\n{text[:1500]}"
        )
        outcome = generate_deliverable(
            provider, prompt, llm_model, retry_prompt=retry,
            on_progress=(lambda chars: progress_cb(chars)) if progress_cb else None,
        )
        return {"text": outcome["text"], "model": llm_model,
                "attempts": outcome["attempts"], "hint": outcome["hint"]}

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
        ocr_parts, ocr_model = [], ""
        if use_ocr and model_service is not None:
            model = model_service.get_default("vision") or model_service.get_default("llm") or ""
            if model:
                ocr_model = model
                provider = model_service.provider_for(model)
                images = [img for img in self.images.list(ocr_limit, 0, "source_id=?", (source_id,))
                          if (img.get("file_path") or "") and Path(img["file_path"]).exists()]
                if images:
                    from app.services.providers.ollama import OllamaProvider
                    if isinstance(provider, OllamaProvider):
                        ocr_parts = [self._ocr_one_image(provider, model, img) for img in images]
                    else:
                        # API 视觉模型：并发识别，多张图的总耗时接近最慢的那张
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=min(3, len(images))) as pool:
                            ocr_parts = list(pool.map(lambda img: self._ocr_one_image(provider, model, img), images))
                    ocr_parts = [p for p in ocr_parts if p]
        return {"title": title, "content": content[:6000], "ocr_parts": ocr_parts,
                "ocr_model": ocr_model}

    def _ocr_one_image(self, provider, model, img):
        """单张图片识别：返回可拼进素材的文本，失败时返回提示而不抛异常。"""
        path = img.get("file_path") or ""
        try:
            raw = provider.vision(
                "请提取这张图片中的全部文字内容，并用一句话说明图片展示了什么。"
                "只输出：图片说明 + 文字内容。",
                model, path, think=False,
            )
            from app.services.generation_service import clean_llm_text
            text = clean_llm_text(raw)
            return f"[图片·{Path(path).name}] {text[:500]}" if text else ""
        except Exception as exc:
            return f"[图片识别失败] {exc}"

    def build_prompt_card(self, source_id, use_llm=False, model_service=None, use_ocr=True, progress_cb=None):
        """把采集内容规整为可直接用于 AI 图片/视频生成的提示词卡（只保留画面要素，不入库）。"""
        material = self.collect_source_material(source_id, use_ocr=use_ocr, model_service=model_service)
        keywords = self.extract_keywords(material["content"])
        combined = material["content"] + ("\n\n" + "\n".join(material["ocr_parts"]) if material["ocr_parts"] else "")
        if use_llm and model_service is not None:
            llm_model = model_service.get_default("llm") or ""
            if llm_model:
                provider = model_service.provider_for(llm_model)
                from app.services.prompt_quality import DELIVERABLE_RULES, generate_deliverable
                _spec = (
                    "把资料提炼成可直接用于 AI 图片/视频生成的提示词卡。严格输出以下格式：\n"
                    "【English】一行英文正向提示词（逗号分隔，覆盖主体、环境、光线、构图、色彩、风格、质量）\n"
                    "【中文】英文提示词的中文翻译\n"
                    "Negative prompt: 一行负向提示词\n"
                    "建议参数: 若干行（尺寸/时长/镜头/步数等）\n"
                    "要求：只保留与画面相关的要素，剔除广告、导航、版权声明等与画面无关的内容。"
                )
                _card_prompt = (
                    f"{DELIVERABLE_RULES}\n\n=== 本次任务 ===\n{_spec}\n\n=== 资料 ===\n{combined[:6000]}"
                )
                outcome = generate_deliverable(
                    provider, _card_prompt, llm_model,
                    on_progress=(lambda chars: progress_cb(chars)) if progress_cb else None,
                )
                card, hint = outcome["text"], outcome["hint"]
                if card:
                    return {"text": card, "keywords": keywords, "mode": "llm", "model": llm_model, "hint": hint}
                model_hint = hint
            else:
                model_hint = ""
        else:
            model_hint = ""
        keywords_line = ", ".join(keywords) or "无"
        categories = self.match_categories(material["content"], keywords)
        card = (
            "【English 提示词骨架】{subject}, {environment}, {lighting}, {composition}, {style}, ultra detailed\n"
            "【画面要素（由资料提炼）】\n"
            f"- 关键词索引：{keywords_line}\n"
            f"- 自动分类：{' / '.join(categories) or '未匹配'}\n"
            f"- 素材要点：{material['content'][:600]}\n"
            + ("\n【图片识别内容】\n" + "\n".join(material["ocr_parts"]) + "\n" if material["ocr_parts"] else "")
            + "\n（未调用大模型：以上为按资料提炼的骨架，可在模型中心设置默认 LLM 后重新规整为完整成品提示词）"
        )
        return {"text": card, "keywords": keywords, "mode": "keyword", "model": "", "hint": model_hint}

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
                    model_name, think=False,
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
