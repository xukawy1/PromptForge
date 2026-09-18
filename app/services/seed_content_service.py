from __future__ import annotations

import json
from pathlib import Path

from app.database.repositories.core import KnowledgeRepository, PromptRepository, CategoryRepository
from app.services.collector_service import CollectorService


class SeedContentService:
    """内置内容包：一键导入官方提示词知识卡片与成品 Prompt（按标题/哈希幂等，可重复执行）。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self.knowledge = KnowledgeRepository(db_path)
        self.prompts = PromptRepository(db_path)
        self.categories = CategoryRepository(db_path)

    @staticmethod
    def resource_file() -> Path:
        return Path(__file__).resolve().parents[1] / "resources" / "builtin_prompts.json"

    @staticmethod
    def components_resource_file() -> Path:
        return Path(__file__).resolve().parents[1] / "resources" / "builtin_components.json"

    def import_components_templates(self, resource_path: Path | None = None):
        """预置提示词组件（含写法变体）与 Prompt 模板（含变量），按名称幂等。"""
        from app.database.repositories.core import ComponentRepository, ComponentVariantRepository, TemplateRepository
        path = Path(resource_path) if resource_path else self.components_resource_file()
        if not path.exists():
            raise FileNotFoundError(f"内置组件/模板包缺失：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        components_repo = ComponentRepository(self.db_path)
        variants_repo = ComponentVariantRepository(self.db_path)
        templates_repo = TemplateRepository(self.db_path)

        added_components = 0
        for comp in data.get("components", []):
            canonical = (comp.get("canonical_name") or "").strip()
            if not canonical or components_repo.list(1, 0, "canonical_name=?", (canonical,)):
                continue
            component_id = components_repo.create({
                "canonical_name": canonical,
                "name_zh": comp.get("name_zh"), "name_en": comp.get("name_en"),
                "category_id": self._category_id(comp.get("category") or ""),
                "description": comp.get("description"), "usage_context": comp.get("usage_context"),
                "confidence": 1.0,
            })
            for variant in comp.get("variants", []):
                variants_repo.create({"component_id": component_id, "variant_text": variant, "language": "en"})
            added_components += 1

        added_templates = 0
        from app.services.pattern_service import PatternService
        pattern_service = PatternService(self.db_path)
        for tpl in data.get("templates", []):
            name = (tpl.get("name") or "").strip()
            if not name or templates_repo.list(1, 0, "name=?", (name,)):
                continue
            variables = tpl.get("variables", [])
            template_id = pattern_service.create_template(
                {"name": name, "description": tpl.get("description") or "", "template_content": tpl.get("template_content") or "",
                 "target_model": tpl.get("target_model") or "", "language": tpl.get("language") or "en",
                 "version": "1.0", "is_system": 1},
                variables,
            )
            added_templates += 1
        return {"components": added_components, "templates": added_templates}

    def _category_id(self, name):
        for row in self.categories.list(500):
            if row["name"] == name:
                return row["id"]
        return None

    def import_builtin(self, resource_path: Path | None = None):
        path = Path(resource_path) if resource_path else self.resource_file()
        if not path.exists():
            raise FileNotFoundError(f"内置内容包缺失：{path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        added_cards, added_prompts = 0, 0

        existing_titles = {row["title"] for row in self.knowledge.list(2000)}
        for card in data.get("knowledge_cards", []):
            title = (card.get("title") or "").strip()
            if not title or title in existing_titles:
                continue
            self.knowledge.create({
                "source_type": "builtin", "source_id": None,
                "title": title,
                "content": card.get("content") or "",
                "summary": "关键词：" + (card.get("keywords") or ""),
                "category_id": self._category_id(card.get("category") or ""),
                "knowledge_type": "prompt_template",
                "confidence": 1.0,
            })
            existing_titles.add(title)
            added_cards += 1

        for item in data.get("prompts", []):
            prompt_text = (item.get("prompt") or "").strip()
            if not prompt_text:
                continue
            content_hash = CollectorService.hash_bytes(prompt_text.encode("utf-8"))
            if self.prompts.list(1, 0, "content_hash=?", (content_hash,)):
                continue
            prompt_id = self.prompts.create({
                "title": (item.get("title") or "内置提示词").strip(),
                "prompt_text": prompt_text,
                "negative_prompt": item.get("negative") or None,
                "prompt_type": "image",
                "language": "en",
                "content_hash": content_hash,
                "analysis_result": json.dumps({"translation_zh": item.get("zh") or ""}, ensure_ascii=False),
                "analysis_status": "builtin",
            })
            self.knowledge.create({
                "source_type": "prompt", "source_id": prompt_id,
                "title": (item.get("title") or "内置提示词").strip(),
                "content": prompt_text + (("\n\nNegative prompt: " + item["negative"]) if item.get("negative") else ""),
                "summary": "关键词：" + (item.get("zh") or "")[:80],
                "category_id": self._category_id(item.get("category") or ""),
                "knowledge_type": "prompt",
                "confidence": 1.0,
            })
            added_prompts += 1

        return {"knowledge_cards": added_cards, "prompts": added_prompts}

    def install_skills_from_dir(self, skills_dir, skill_service):
        """把 skills 目录下的每个 .md 文件/子文件夹安装为 Skill（幂等：重复安装即更新）。"""
        skills_dir = Path(skills_dir)
        if not skills_dir.exists():
            return []
        installed = []
        # 已按来源路径安装过的（含用户重命名后的）直接跳过，避免重复安装产生副本
        existing_paths = set()
        try:
            for row in skill_service.list_skills(1000):
                if row.get("source_path"):
                    existing_paths.add(str(row["source_path"]))
        except Exception:
            pass
        for item in sorted(skills_dir.iterdir()):
            if item.is_dir() or item.suffix.lower() in (".md", ".markdown", ".txt"):
                if str(item) in existing_paths:
                    continue
                try:
                    outcome = skill_service.install_from_path(item)
                    installed.append(outcome)
                except (ValueError, OSError):
                    continue
        return installed
