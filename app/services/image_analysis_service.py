from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.database.repositories.core import ImageRepository, PromptRepository, SourceRepository


class ImageAnalysisService:
    """图片反推服务：Metadata 解析 + AI 视觉反推（图片→多模态模型→提示词）。

    Metadata 链解析生成图内嵌的 A1111 parameters / ComfyUI 工作流；
    Vision 链参照本地多模态工作流（如 ComfyUI-llama-TE：图片 → VLM → 提示词）
    的原理，通过 Ollama 的视觉模型看图反推提示词，模型与反推指令均可配置。
    """

    VISION_SYSTEM = "你是专业的 AI 绘画提示词反推专家。只输出提示词与参数，不要寒暄和多余解释。"
    DEFAULT_VISION_PROMPT = (
        "仔细观察这张图片，反推出能够生成与之高度相似画面的 AI 绘画提示词，按以下格式输出：\n"
        "第一行：一行英文正向提示词，用逗号分隔（覆盖主体、风格、光线、构图、画质等要素）\n"
        "第二行：Negative prompt: 一行负向提示词\n"
        "最后：用两三句中文说明画面要点与风格判断依据。"
    )

    def __init__(self, db_path):
        self.db_path = db_path
        self.images = ImageRepository(db_path)
        self.prompts = PromptRepository(db_path)
        self.sources = SourceRepository(db_path)

    # ---------- 本地解析 ----------

    @staticmethod
    def extract_metadata(path: str | Path) -> dict[str, Any]:
        """读取 PNG tEXt/iTXt 与 JPEG EXIF 等内嵌文本字段。"""
        from PIL import Image
        from PIL.ExifTags import TAGS

        path = Path(path)
        data: dict[str, Any] = {}
        with Image.open(path) as im:
            info = getattr(im, "info", {}) or {}
            for key, value in info.items():
                if isinstance(value, (str, int, float)):
                    data[str(key)] = value
            try:
                exif = im.getexif()
                for tag_id, value in exif.items():
                    name = TAGS.get(tag_id, str(tag_id))
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "ignore")
                    if isinstance(value, (str, int, float)):
                        data.setdefault(f"EXIF:{name}", value)
            except Exception:
                pass
        return data

    @staticmethod
    def parse_a1111_parameters(text: str) -> dict[str, Any]:
        """解析 Stable Diffusion WebUI 的 parameters 文本块。"""
        lines = (text or "").replace("\r\n", "\n").splitlines()
        positive, negative, settings = [], [], {}
        mode = "positive"
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            steps_match = re.match(r"^Steps:\s*(.*)$", stripped, re.I)
            neg_match = re.match(r"^Negative prompt:\s*(.*)$", stripped, re.I)
            if steps_match:
                mode = "settings"
                first, _, remainder = steps_match.group(1).partition(",")
                settings["Steps"] = first.strip()
                for part in remainder.split(","):
                    if ":" in part:
                        key, value = part.split(":", 1)
                        settings[key.strip()] = value.strip()
                continue
            if neg_match:
                mode = "negative"
                if neg_match.group(1):
                    negative.append(neg_match.group(1))
                continue
            (positive if mode == "positive" else negative if mode == "negative" else []).append(stripped)
        size = settings.get("Size", "")
        if "x" in size:
            width, _, height = size.partition("x")
            settings.setdefault("Width", width.strip())
            settings.setdefault("Height", height.strip())
        return {
            "tool": "a1111",
            "positive": ", ".join(positive).strip(),
            "negative": ", ".join(negative).strip(),
            "settings": settings,
        }

    @staticmethod
    def parse_comfyui_workflow(text: str) -> dict[str, Any]:
        """解析 ComfyUI 导出的 prompt 工作流 JSON，提取正向/负向文本与采样参数。"""
        try:
            nodes = json.loads(text)
        except (TypeError, ValueError):
            return {"tool": "comfyui", "positive": "", "negative": "", "settings": {}, "error": "工作流 JSON 无法解析"}
        if not isinstance(nodes, dict):
            return {"tool": "comfyui", "positive": "", "negative": "", "settings": {}, "error": "工作流格式不是节点字典"}

        def node_text(node_id):
            node = nodes.get(str(node_id)) or {}
            value = (node.get("inputs") or {}).get("text")
            return value.strip() if isinstance(value, str) else ""

        positive, negative = [], []
        settings: dict[str, Any] = {}
        for node in nodes.values():
            node = node if isinstance(node, dict) else {}
            class_type = str(node.get("class_type") or "")
            inputs = node.get("inputs") or {}
            if class_type == "KSampler":
                positive.append(node_text((inputs.get("positive") or [None])[0]))
                negative.append(node_text((inputs.get("negative") or [None])[0]))
                for key in ("steps", "cfg", "seed", "sampler_name", "scheduler", "denoise"):
                    if key in inputs:
                        settings[key] = inputs[key]
            elif class_type == "CheckpointLoaderSimple":
                if inputs.get("ckpt_name"):
                    settings["model"] = inputs["ckpt_name"]
            elif class_type == "CLIPTextEncode":
                text_value = inputs.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    positive.append(text_value.strip())
        return {
            "tool": "comfyui",
            "positive": ", ".join([t for t in positive if t]),
            "negative": ", ".join([t for t in negative if t]),
            "settings": settings,
        }

    @classmethod
    def parse_generation_metadata(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """按文件格式标准识别生成工具与正/负向 Prompt。"""
        for key in ("parameters", "Parameters"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                result = cls.parse_a1111_parameters(raw[key])
                result["source_key"] = key
                return result
        for key in ("prompt", "Prompt"):
            if isinstance(raw.get(key), (str, dict)):
                text = raw[key] if isinstance(raw[key], str) else json.dumps(raw[key], ensure_ascii=False)
                result = cls.parse_comfyui_workflow(text)
                result["source_key"] = key
                return result
        return {"tool": "none", "positive": "", "negative": "", "settings": {}}

    @classmethod
    def analyze_path(cls, path: str | Path) -> dict[str, Any]:
        path = Path(path)
        raw = cls.extract_metadata(path)
        parsed = cls.parse_generation_metadata(raw)
        return {"file_path": str(path), "file_name": path.name, "raw_keys": sorted(raw.keys()), **parsed}

    # ---------- AI 视觉反推 ----------

    def vision_analyze(self, image_path, model_service, instruction=None):
        """用多模态模型看图反推提示词。优先默认 Vision 模型，其次默认 LLM。"""
        if model_service is None:
            raise RuntimeError("模型服务尚未初始化")
        model = model_service.get_default("vision") or model_service.get_default("llm")
        if not model:
            from app.services.generation_service import MODEL_HINT
            raise RuntimeError(MODEL_HINT)
        provider = model_service.provider_for(model)
        raw = provider.vision(instruction or self.DEFAULT_VISION_PROMPT, model, image_path, system=self.VISION_SYSTEM)
        from app.services.generation_service import clean_llm_text
        return {"model": model, "image_path": str(image_path), "text": clean_llm_text(raw)}

    def save_prompt_text(self, text, image_id=None, title=""):
        """把反推文本（英文提示词 + Negative prompt + 中文说明）保存为 Prompt。"""
        from app.services.generation_service import GenerationService
        from app.services.collector_service import CollectorService
        parsed = GenerationService.parse_result(text)
        positive = (parsed.get("en") or parsed.get("positive") or "").strip()
        if not positive:
            raise ValueError("反推结果没有可保存的正向 Prompt")
        content_hash = CollectorService.hash_bytes(positive.encode("utf-8"))
        existing = self.prompts.list(1, 0, "content_hash=?", (content_hash,))
        if existing:
            return {"status": "duplicate", "prompt_id": existing[0]["id"], "message": "相同 Prompt 已存在"}
        image_row = self.images.get(image_id) if image_id else None
        fallback_title = "图片反推：" + Path(image_row["file_path"]).stem if image_row else "图片反推：" + Path(image_id or "未命名").stem
        prompt_id = self.prompts.create({
            "source_id": image_row.get("source_id") if image_row else None,
            "image_id": image_id,
            "title": (title or "").strip() or fallback_title,
            "prompt_text": positive,
            "negative_prompt": parsed.get("negative") or None,
            "prompt_type": "image",
            "language": "en",
            "content_hash": content_hash,
            "analysis_result": json.dumps({"translation_zh": parsed.get("zh") or "", "params": parsed.get("params") or ""}, ensure_ascii=False),
            "analysis_status": "analyzed",
        })
        return {"status": "created", "prompt_id": prompt_id, "message": "已保存到 Prompt 库"}

    # ---------- 数据库联动 ----------

    def list_images(self, limit=200):
        return self.images.list(limit=limit)

    def analyze_image(self, image_id):
        row = self.images.get(image_id)
        if not row:
            raise ValueError("图片记录不存在")
        file_path = row.get("file_path") or ""
        if not Path(file_path).exists():
            raise ValueError("图片文件不存在，可能已被移动或删除")
        analysis = self.analyze_path(file_path)
        try:
            metadata = json.loads(row.get("metadata") or "{}")
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["generation_metadata"] = analysis
        self.images.update(image_id, {
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "analysis_status": "analyzed",
        })
        return {"image_id": image_id, **analysis}

    def save_as_prompt(self, image_id, title="", prompt_type="image", language="zh"):
        row = self.images.get(image_id)
        if not row:
            raise ValueError("图片记录不存在")
        try:
            metadata = json.loads(row.get("metadata") or "{}")
        except (TypeError, ValueError):
            metadata = {}
        analysis = metadata.get("generation_metadata")
        if not isinstance(analysis, dict) or not (analysis.get("positive") or "").strip():
            analysis = self.analyze_image(image_id)
        positive = (analysis.get("positive") or "").strip()
        if not positive:
            raise ValueError("该图片没有可保存的正向 Prompt")
        from app.services.collector_service import CollectorService
        content_hash = CollectorService.hash_bytes(positive.encode("utf-8"))
        existing = self.prompts.list(1, 0, "content_hash=?", (content_hash,))
        if existing:
            return {"status": "duplicate", "prompt_id": existing[0]["id"], "message": "相同 Prompt 已存在"}
        prompt_id = self.prompts.create({
            "source_id": row.get("source_id"), "image_id": image_id,
            "title": (title or "").strip() or f"图片反推：{Path(row.get('file_path') or '未命名').stem}",
            "prompt_text": positive,
            "negative_prompt": (analysis.get("negative") or "").strip() or None,
            "prompt_type": prompt_type or "image",
            "language": language or "zh",
            "content_hash": content_hash,
            "analysis_result": json.dumps(analysis.get("settings") or {}, ensure_ascii=False),
            "analysis_status": "analyzed",
        })
        return {"status": "created", "prompt_id": prompt_id, "message": "已保存到 Prompt 库"}
