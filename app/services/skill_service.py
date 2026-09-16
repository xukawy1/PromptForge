from __future__ import annotations

import json
from pathlib import Path

from app.database.repositories.core import SkillRepository, KnowledgeRepository, PromptRepository
from app.services.collector_service import CollectorService

MAX_SKILL_BYTES = 200 * 1024
MAX_SKILL_FILES = 20
SKILL_SUFFIXES = {".md", ".markdown", ".txt"}


class SkillService:
    """Skill 工坊：安装本地 skill 文件/文件夹，按关键字目录组织，并可按 skill 格式改写提示词素材。

    安装：读取 markdown/txt 内容（文件夹则合并其中 skill 文件），关键字取文件/文件夹名；
    调用：点击关键字 → 选知识库提示词素材 → 大模型按 skill 格式改写（无模型时规则拼接）。
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self.repo = SkillRepository(db_path)
        self.knowledge = KnowledgeRepository(db_path)
        self.prompts = PromptRepository(db_path)

    # ---------- 安装 ----------

    @staticmethod
    def collect_skill_files(path: Path):
        path = Path(path)
        if path.is_file():
            if path.suffix.lower() not in SKILL_SUFFIXES:
                raise ValueError("仅支持 .md / .markdown / .txt 的 skill 文件，或包含它们的文件夹")
            return [(path.name, path.read_text(encoding="utf-8", errors="ignore"))], path
        if not path.is_dir():
            raise ValueError("路径不存在")
        files = []
        total = 0
        for item in sorted(path.rglob("*")):
            if len(files) >= MAX_SKILL_FILES or total >= MAX_SKILL_BYTES:
                break
            if item.is_file() and item.suffix.lower() in SKILL_SUFFIXES:
                text = item.read_text(encoding="utf-8", errors="ignore")[:MAX_SKILL_BYTES]
                files.append((str(item.relative_to(path)), text))
                total += len(text.encode("utf-8"))
        if not files:
            raise ValueError("文件夹中没有找到 .md / .txt 的 skill 文件")
        return files, path

    def install_from_path(self, path) -> dict:
        files, base = self.collect_skill_files(Path(path))
        # 单文件安装：关键字取文件名（去掉扩展名）；文件夹安装：取文件夹名。
        keyword = (base.stem if base.is_file() else base.name).strip() or "skill"
        sections = []
        for name, text in files:
            sections.append(f"## 来源文件：{name}\n\n{text.strip()}")
        content = "\n\n---\n\n".join(sections)[:MAX_SKILL_BYTES]
        description = next((t for t in content.splitlines() if t.strip() and not t.strip().startswith("#")), "")[:160]
        existing = self.repo.list(1, 0, "keyword=?", (keyword,))
        if existing:
            self.repo.update(existing[0]["id"], {
                "name": keyword, "description": description, "content": content,
                "source_path": str(base), "file_count": len(files),
            })
            return {"status": "updated", "skill_id": existing[0]["id"], "keyword": keyword, "file_count": len(files)}
        skill_id = self.repo.create({
            "keyword": keyword, "name": keyword, "description": description,
            "content": content, "source_path": str(base), "file_count": len(files),
        })
        return {"status": "created", "skill_id": skill_id, "keyword": keyword, "file_count": len(files)}

    # ---------- 管理 ----------

    def list_skills(self, limit=200):
        return self.repo.list(limit=limit)

    def get(self, skill_id):
        return self.repo.get(skill_id)

    def delete(self, skill_id):
        return self.repo.delete(skill_id)

    # ---------- 应用 ----------

    def prompt_materials(self, limit=200):
        """知识库中可作为素材的提示词条目（含 Prompt 库同步条目）。"""
        rows = self.knowledge.list(limit=limit)
        return [r for r in rows if (r.get("content") or "").strip()]

    @staticmethod
    def _system_excerpt(content: str, limit: int = 5000) -> str:
        """截取 skill 的核心规范用于系统提示词：
        优先 SKILL.md 内容，其次按文件顺序拼接；超出 limit 截断，避免超出模型上下文导致空输出。"""
        content = content or ""
        if len(content) <= limit:
            return content
        sections = content.split("\n\n---\n\n")
        preferred, others = [], []
        for section in sections:
            head = section[:200]
            (preferred if "SKILL.md" in head else others).append(section)
        result, used = [], 0
        for section in preferred + others:
            if used + len(section) > limit and result:
                break
            result.append(section[: max(0, limit - used)])
            used += len(section)
            if used >= limit:
                break
        excerpt = "\n\n---\n\n".join(result)[:limit]
        return excerpt + "\n\n（以上为 skill 核心规范节选；如需更多细节以 skill 原文为准）"

    def apply_skill(self, skill_id, material, model_service=None, on_progress=None):
        """按 skill 格式生成提示词：有默认 LLM 时调用模型，否则规则拼接。

        防空白策略：系统提示词按核心规范节选（避免超长超上下文）→ 模型返回为空时
        自动用更短提示词重试一次 → 仍为空则规则拼接兜底，保证结果永不空白。
        """
        skill = self.repo.get(skill_id)
        if not skill:
            raise ValueError("Skill 不存在")
        material = (material or "").strip()
        if not material:
            raise ValueError("请先选择提示词素材")
        if on_progress:
            on_progress(20)
        model_name = ""
        if model_service is not None:
            model_name = model_service.get_default("llm") or ""

        def _rule_text(note="（未连接大模型，以下为 skill 格式 + 素材的规则拼接）"):
            return (
                f"{note}\n\n"
                f"=== Skill 格式说明（{skill.get('keyword')}）===\n{self._system_excerpt(skill.get('content') or '', 4000)}\n\n"
                f"=== 提示词素材 ===\n{material}"
            )

        if model_name:
            if on_progress:
                on_progress(40)
            provider = model_service.provider_for(model_name)
            from app.services.generation_service import clean_llm_text
            task = (
                "你是提示词创作专家。请深入理解下方 skill 所规定的书写格式、结构与要求，"
                "把提示词素材进行详细扩充和完善：补全画面细节（主体特征、环境、光线、构图、色彩、氛围、质量要素），"
                "并严格按照 skill 规范的格式与流程组织，输出一份完整、可直接使用的成品提示词。"
                "只输出成品本身，不要解释。"
            )
            text = ""
            try:
                text = clean_llm_text(provider.generate(
                    f"{task}\n\n=== 提示词素材 ===\n{material}",
                    model_name,
                    system=self._system_excerpt(skill.get("content") or "", 6000),
                    options={"num_predict": 3072},
                ))
            except Exception:
                text = ""
            if not text:
                # 空结果重试：更短的规范 + 更直接的指令
                if on_progress:
                    on_progress(65)
                try:
                    text = clean_llm_text(provider.generate(
                        f"{task}\n\n只输出成品提示词。\n\n=== 提示词素材 ===\n{material[:2000]}",
                        model_name,
                        system=self._system_excerpt(skill.get("content") or "", 2500),
                        options={"num_predict": 2048},
                    ))
                except Exception:
                    text = ""
            if text:
                mode = "llm"
            else:
                # 最终兜底：规则拼接（保证结果不为空，并明确标注原因）
                text = _rule_text("（模型未返回内容——可能因 skill 文档较长超出模型上下文，以下为规则拼接版；"
                                  "可更换更大的模型或在模型中心调大上下文后重试）")
                mode = "rule_fallback"
        else:
            text = _rule_text()
            mode = "rule"
        if on_progress:
            on_progress(95)
        return {"mode": mode, "model": model_name, "skill_keyword": skill.get("keyword"), "text": text}

    # ---------- 轻量素材索引（供 Skill 工坊快速加载） ----------

    def list_material_index(self, limit=400):
        """只取素材的轻量字段（不含正文），进入页面秒开；正文按需再取。"""
        from app.database.connection import create_connection
        with create_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, title, category_id, created_at FROM knowledge_items "
                "WHERE content IS NOT NULL AND TRIM(content) != '' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_material_content(self, material_id) -> str:
        """按需获取某条素材的正文。"""
        from app.database.connection import create_connection
        with create_connection(self.db_path) as conn:
            row = conn.execute("SELECT content FROM knowledge_items WHERE id=?", (material_id,)).fetchone()
            return (row["content"] if row else "") or ""

    def category_name_map(self) -> dict:
        """分类 id → 名称映射（一次查询，替代逐条查询）。"""
        from app.database.connection import create_connection
        with create_connection(self.db_path) as conn:
            rows = conn.execute("SELECT id, name FROM categories").fetchall()
            return {r["id"]: r["name"] for r in rows}


    def save_result_as_prompt(self, text, title=""):
        from app.services.generation_service import GenerationService
        parsed = GenerationService.parse_result(text)
        positive = (parsed.get("en") or parsed.get("positive") or "").strip()
        if not positive:
            raise ValueError("结果没有可保存的正向 Prompt")
        content_hash = CollectorService.hash_bytes(positive.encode("utf-8"))
        existing = self.prompts.list(1, 0, "content_hash=?", (content_hash,))
        if existing:
            return {"status": "duplicate", "prompt_id": existing[0]["id"], "message": "相同 Prompt 已存在"}
        prompt_id = self.prompts.create({
            "title": (title or "").strip() or "Skill 生成：" + positive[:24],
            "prompt_text": positive,
            "negative_prompt": parsed.get("negative") or None,
            "prompt_type": "prompt",
            "language": "en",
            "content_hash": content_hash,
            "analysis_result": json.dumps({"translation_zh": parsed.get("zh") or "", "params": parsed.get("params") or ""}, ensure_ascii=False),
            "analysis_status": "generated",
        })
        return {"status": "created", "prompt_id": prompt_id, "message": "已保存到 Prompt 库"}

    def save_result_to_knowledge(self, text, skill_id, title="", category_id=None):
        from app.services.generation_service import GenerationService
        skill = self.repo.get(skill_id)
        parsed = GenerationService.parse_result(text)
        content = parsed.get("en") or (parsed.get("positive") or "").strip()
        if not content:
            raise ValueError("结果没有可保存的内容")
        payload = {"translation_zh": parsed.get("zh") or "", "negative": parsed.get("negative") or "", "params": parsed.get("params") or ""}
        return self.knowledge.create({
            "source_type": "skill_result", "source_id": skill_id,
            "title": (title or "").strip() or f"Skill 成品：{skill.get('keyword') if skill else ''}",
            "content": content, "summary": json.dumps(payload, ensure_ascii=False),
            "category_id": category_id, "knowledge_type": "prompt", "confidence": 1.0,
        })
