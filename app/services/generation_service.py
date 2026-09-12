from __future__ import annotations

import json
from app.database.connection import create_connection
from app.database.repositories.core import GenerationHistoryRepository, ModelRepository
from app.services.knowledge_service import KnowledgeService
from app.services.model_service import ModelService

MODEL_HINT = "尚未设置默认模型：请打开「模型中心」，点击“测试连接并刷新模型”，再选择模型设为默认 LLM/Vision。"

SYSTEM_PROMPT = (
    "你是专业的 AI 绘画与视频提示词工程师。根据用户需求生成高质量提示词。"
    "若用户提供了模板，必须严格遵循模板的结构、变量语义与风格进行详细扩写，不得偏离模板框架。"
    "必须严格按以下格式输出，不要输出多余解释：\n"
    "【English】\n一行英文正向提示词，用逗号分隔关键词与短语\n"
    "【中文】\n上面英文提示词的准确中文翻译，便于用户理解\n"
    "Negative prompt: 一行负向提示词\n"
    "随后可用若干行给出建议参数（如 Steps、CFG、尺寸、镜头、时长等）。"
)


def clean_llm_text(raw: str) -> str:
    """清洗模型输出：优先取 </think> 之后的内容（思考型模型），否则剥离成对 think 块。"""
    text = (raw or "").strip()
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


class GenerationService:
    """Prompt 生成服务：需求 → 上下文检索 → 模型生成 → 历史与 Prompt 库。"""

    def __init__(self, db_path, config, model_service: ModelService, knowledge_service: KnowledgeService | None = None, pattern_service=None):
        self.db_path = db_path
        self.config = config
        self.model_service = model_service
        self.knowledge = knowledge_service
        self.pattern_service = pattern_service
        self.history_repo = GenerationHistoryRepository(db_path)
        self.models_repo = ModelRepository(db_path)

    # ---------- 上下文检索（关键词 RAG） ----------

    def retrieve_context(self, keyword, limit=5):
        keyword = (keyword or "").strip()
        if not keyword or not self.knowledge:
            return []
        context = []
        seen_texts = set()

        def add(kind, title, content):
            text = (content or "").strip()
            if not text or text in seen_texts:
                return
            seen_texts.add(text)
            context.append({"type": kind, "title": title, "snippet": text[:400]})

        for row in self.knowledge.list_knowledge(None, keyword, 1, limit):
            add("knowledge", row.get("title") or "", row.get("content") or row.get("summary"))
        for row in self.knowledge.prompts.search_text(keyword, limit=limit):
            add("prompt", row.get("title") or "", row.get("prompt_text"))
        if len(context) >= limit:
            return context[:limit]
        with create_connection(self.db_path) as conn:
            like = f"%{keyword}%"
            rows = conn.execute(
                "SELECT title, content FROM documents WHERE title LIKE ? OR content LIKE ? OR summary LIKE ? ORDER BY id DESC LIMIT ?",
                (like, like, like, limit),
            ).fetchall()
        for row in rows:
            add("document", row["title"], row["content"])
        return context[:limit]

    # ---------- Prompt 组装 ----------

    @staticmethod
    def fill_template(template_content, variables):
        text = template_content or ""
        for name, value in (variables or {}).items():
            text = text.replace("{" + name + "}", str(value or ""))
        return text

    def build_generation_prompt(self, user_input, template=None, variables=None, context=None):
        parts = []
        requirement = (user_input or "").strip()
        if template:
            filled = self.fill_template(template.get("template_content"), variables)
            parts.append(f"请基于以下模板生成：\n{filled}")
            if requirement:
                parts.append(f"补充需求：{requirement}")
        else:
            parts.append(f"用户需求：{requirement}")
        if context:
            lines = ["参考资料（生成时可参考其中的风格与要素）："]
            for item in context:
                lines.append(f"- [{item['type']}] {item['title']}：{item['snippet']}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    # ---------- 生成与持久化 ----------

    def generate(self, user_input, template_id=None, variables=None, use_context=False, on_chunk=None):
        model_name = self.model_service.get_default("llm")
        if not model_name:
            raise RuntimeError(MODEL_HINT)
        template = None
        if template_id and self.pattern_service:
            template = self.pattern_service.templates.get(template_id)
            if not template:
                raise ValueError("模板不存在")
        context = self.retrieve_context(user_input) if use_context else []
        prompt = self.build_generation_prompt(user_input, template, variables, context)
        provider = self.model_service.provider()
        if on_chunk is not None:
            result = provider.generate_stream(prompt, model_name, system=SYSTEM_PROMPT, on_chunk=on_chunk)
        else:
            result = provider.generate(prompt, model_name, system=SYSTEM_PROMPT)
        record = self.save_history(user_input, result, template_id=template_id, retrieved_context=json.dumps(context, ensure_ascii=False) if context else "")
        return {"model": model_name, "prompt": prompt, "result": result, "context": context, "history_id": record}

    def save_history(self, user_input, prompt_result, negative_prompt=None, template_id=None, retrieved_context=""):
        model_name = self.model_service.get_default("llm")
        model_id = None
        if model_name:
            rows = self.models_repo.list(1, 0, "name=?", (model_name,))
            model_id = rows[0]["id"] if rows else None
        return self.history_repo.create({
            "user_input": user_input or "", "prompt_result": prompt_result or "",
            "negative_prompt": negative_prompt, "model_id": model_id,
            "template_id": template_id, "retrieved_context": retrieved_context or "",
        })

    def list_history(self, limit=20):
        return self.history_repo.list(limit=limit)

    # ---------- 翻译 ----------

    TRANSLATION_LANGUAGES = ["中文（简体）", "中文（繁体）", "English", "日本語", "한국어", "Français",
                             "Deutsch", "Español", "Português", "Italiano", "Русский", "العربية",
                             "ไทย", "Tiếng Việt", "Bahasa Indonesia", "Türkçe", "Polski", "Nederlands"]

    def translate(self, text, target_lang="中文（简体）"):
        text = (text or "").strip()
        if not text:
            raise ValueError("没有需要翻译的内容")
        model_name = self.model_service.get_default("llm")
        if not model_name:
            raise RuntimeError(MODEL_HINT)
        provider = self.model_service.provider()
        result = provider.generate(
            f"Translate the following text into {target_lang}. "
            f"Only output the translation, nothing else.\n\n{text[:6000]}",
            model_name,
            system="You are a professional translator. Preserve the original meaning and tone. Only output the translation.",
        )
        return clean_llm_text(result)

    # ---------- 结果解析与入库 ----------

    @staticmethod
    def parse_result(result):
        """把模型输出拆为英文/中文/负向与参数；无标记时整体作为英文正向。"""
        text = clean_llm_text(result)

        en_part, zh_part, remainder = text, "", ""
        en_idx = text.find("【英文】")
        zh_idx = text.find("【中文】")
        has_markers = en_idx >= 0 and zh_idx > en_idx
        if has_markers:
            en_part = text[en_idx + len("【英文】"):zh_idx].strip()
            tail = text[zh_idx + len("【中文】"):].strip()
            neg_idx = tail.lower().find("negative prompt:")
            if neg_idx >= 0:
                zh_part = tail[:neg_idx].strip()
                remainder = tail[neg_idx:]
            else:
                zh_part = tail
        else:
            remainder = text
            neg_idx = text.lower().find("negative prompt:")
            if neg_idx >= 0:
                en_part = text[:neg_idx].strip()
                remainder = text[neg_idx:]

        negative, params = "", ""
        lower_remainder = remainder.lower()
        neg_idx = lower_remainder.find("negative prompt:")
        if neg_idx >= 0:
            after = remainder[neg_idx + len("negative prompt:"):].strip()
            lines = after.splitlines()
            negative_lines, consumed = [], 0
            for line in lines:
                stripped = line.strip()
                if stripped and not negative_lines:
                    negative_lines.append(stripped); consumed += 1; continue
                if not stripped and negative_lines and consumed == len(negative_lines):
                    consumed += 1; continue
                break
            negative = " ".join(negative_lines)
            params = "\n".join(lines[consumed:]).strip()
        elif has_markers and remainder:
            params = remainder.strip()
        return {"positive": en_part, "en": en_part, "zh": zh_part, "negative": negative, "params": params}

    def save_as_prompt(self, result_text, title="", prompt_type="image", language="en"):
        from app.services.collector_service import CollectorService
        from app.database.repositories.core import PromptRepository
        parsed = self.parse_result(result_text)
        positive = parsed["positive"].strip()
        if not positive:
            raise ValueError("生成结果没有可保存的正向 Prompt")
        prompts = PromptRepository(self.db_path)
        content_hash = CollectorService.hash_bytes(positive.encode("utf-8"))
        existing = prompts.list(1, 0, "content_hash=?", (content_hash,))
        if existing:
            return {"status": "duplicate", "prompt_id": existing[0]["id"], "message": "相同 Prompt 已存在"}
        prompt_id = prompts.create({
            "title": (title or "").strip() or f"AI生成：{(positive or '')[:24]}…",
            "prompt_text": positive,
            "negative_prompt": parsed["negative"] or None,
            "prompt_type": prompt_type or "image",
            "target_model": self.model_service.get_default("llm") or None,
            "language": language or "en",
            "content_hash": content_hash,
            "analysis_result": json.dumps({"translation_zh": parsed.get("zh") or "", "params": parsed.get("params") or ""}, ensure_ascii=False),
            "analysis_status": "generated",
        })
        return {"status": "created", "prompt_id": prompt_id, "message": "已保存到 Prompt 库（含中文翻译）"}
