from __future__ import annotations

import json
import re
import time
from pathlib import Path

from app.database.repositories.core import SkillRepository, KnowledgeRepository, PromptRepository
from app.services.collector_service import CollectorService
from app.services.prompt_quality import (
    DELIVERABLE_RULES, clean_deliverable, looks_degenerate, stream_generate, switch_model_hint,
)

MAX_SKILL_BYTES = 200 * 1024
MAX_SKILL_FILES = 20
SKILL_SUFFIXES = {".md", ".markdown", ".txt"}

# 成品提示词的输出上限：一张完整设定卡/分镜脚本本身就超过 3000 token，上限过小会被截在半途。
# 本机实测 Ollama 默认上下文远大于此值（6000+ token 可跑满），故只抬 num_predict、不动 num_ctx。
SKILL_NUM_PREDICT = 8192
SKILL_NUM_PREDICT_RETRY = 4096
SKILL_STREAM_CHARS = 9000  # 流式进度按累计字数估算的比例基准
SKILL_MAX_CONTINUATIONS = 2  # 成品被输出上限截断时，最多自动续写几次
# 本地小模型写长结构化成品时容易陷入重复循环（Ollama 会以 "token repeat limit reached" 中止），
# 适度加大重复惩罚与回看窗口可显著减少退化。
SKILL_SAMPLING = {"repeat_penalty": 1.2, "repeat_last_n": 512}

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

    def update_skill(self, skill_id, content=None, description=None):
        """编辑 Skill 的详细内容/说明（内容不能为空）。"""
        skill = self.repo.get(skill_id)
        if not skill:
            raise ValueError("Skill 不存在")
        payload = {}
        if content is not None:
            content = str(content).strip()
            if not content:
                raise ValueError("Skill 内容不能为空")
            payload["content"] = content[:200000]
        if description is not None:
            payload["description"] = str(description).strip()[:300]
        if not payload:
            return skill
        self.repo.update(skill_id, payload)
        return self.repo.get(skill_id)

    def rename_skill(self, skill_id, new_name: str):
        """重命名 Skill（下拉列表显示名）：校验非空与唯一后更新 keyword 与 name。"""
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("名称不能为空")
        if len(new_name) > 60:
            raise ValueError("名称过长（60 字以内）")
        skill = self.repo.get(skill_id)
        if not skill:
            raise ValueError("Skill 不存在")
        if new_name == skill.get("keyword"):
            return skill
        if self.repo.list(1, 0, "keyword=?", (new_name,)):
            raise ValueError(f"已存在同名 Skill：{new_name}")
        self.repo.update(skill_id, {"keyword": new_name, "name": new_name})
        return self.repo.get(skill_id)

    # ---------- 应用 ----------

    def prompt_materials(self, limit=200):
        """知识库中可作为素材的提示词条目（含 Prompt 库同步条目）。"""
        rows = self.knowledge.list(limit=limit)
        return [r for r in rows if (r.get("content") or "").strip()]

    @staticmethod
    def _hint_tokens(text: str) -> set:
        """把素材文本切成检索用 token：英文单词 + 中文二元组（无需分词即可衡量相关度）。"""
        text = (text or "").lower()
        tokens = {t for t in re.findall(r"[a-z0-9]{3,}", text)}
        for run in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(run) == 1:
                tokens.add(run)
            for i in range(len(run) - 1):
                tokens.add(run[i:i + 2])
        return tokens

    @classmethod
    def _system_excerpt(cls, content: str, limit: int = 5000, hint: str = "") -> str:
        """截取 skill 的核心规范用于系统提示词。

        排序策略：SKILL.md 永远优先（它是总纲与模板路由）；其余文件按与素材的相关度排序——
        例如素材里出现"东方玄幻/仙侠/神兽"时，eastern-template 会排在 white-template 前面，
        避免靠后的参考文件被 limit 截掉导致规范不全。"""
        content = content or ""
        if len(content) <= limit:
            return content
        sections = content.split("\n\n---\n\n")
        tokens = cls._hint_tokens(hint)
        scored = []
        for index, section in enumerate(sections):
            head = section[:200]
            is_main = "SKILL.md" in head
            score = 0
            if tokens:
                lowered = section.lower()
                score = sum(1 for t in tokens if t in lowered)
            # SKILL.md 置顶；同分保持原文件顺序（稳定）
            scored.append((0 if is_main else 1, -score, index, section))
        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        result, used = [], 0
        for _, _, _, section in scored:
            remaining = limit - used
            if remaining <= 0:
                break
            if len(section) > remaining:
                if result:
                    continue  # 放不下的长文件跳过，继续尝试后面能放下的
                result.append(section[:remaining])  # 一个都放不下时，至少给出最相关文件的开头
                break
            result.append(section)
            used += len(section)
        excerpt = "\n\n---\n\n".join(result)[:limit]
        return excerpt + "\n\n（以上为 skill 核心规范节选；如需更多细节以 skill 原文为准）"

    @staticmethod
    def _looks_degenerate(text: str) -> bool:
        """识别模型退化输出（同一字符或三连串大量重复的乱码）。实现见 prompt_quality。"""
        return looks_degenerate(text)

    @classmethod
    def _clean_deliverable(cls, text: str) -> str:
        """清掉大模型输出里泄漏的 skill 文档痕迹与客套开场白，只留成品正文。"""
        return clean_deliverable(text)

    @staticmethod
    def _generate_text(provider, prompt, model, system, options, on_progress=None, progress_range=(45, 90)) -> str:
        """优先流式生成：成品提示词通常很长，非流式会撞上单次读取超时；流式还能按字数回传进度。"""
        return stream_generate(provider, prompt, model, system=system, options=options,
                               on_progress=on_progress, progress_range=progress_range,
                               stream_chars=SKILL_STREAM_CHARS)

    @staticmethod
    def _strip_overlap(base: str, cont: str, max_overlap: int = 400) -> str:
        """续写结果常常把断点前的尾巴重抄一遍，去掉重叠加的部分。"""
        cont = cont.lstrip()
        for size in range(min(max_overlap, len(cont), len(base)), 24, -1):
            if base.endswith(cont[:size]):
                return cont[size:].lstrip()
        return cont

    @staticmethod
    def _is_truncated(provider, text: str) -> bool:
        """判断成品是否被输出上限截断（Ollama=done_reason:length；API=finish_reason:length）。"""
        if getattr(provider, "last_done_reason", "") in ("length", "aborted"):
            return True
        tail = (text or "").rstrip()
        return tail.endswith(("...", "…", "……")) and len(tail) > 200

    def apply_skill(self, skill_id, material, model_service=None, on_progress=None):
        """按 skill 规范产出【成品提示词】（可直接复制使用），而不是回显 skill 的格式说明。

        防空白/防半截：系统提示词按核心规范节选（SKILL.md 优先 + 与素材相关的参考文件优先）→
        流式长生成（避免单次读取超时）→ 撞上输出上限时自动续写（最多 2 次，拼成完整成品）→
        模型返回为空时用更短的规范重试一次 → 仍为空则规则骨架兜底，保证结果永不空白。
        """
        skill = self.repo.get(skill_id)
        if not skill:
            raise ValueError("Skill 不存在")
        material = (material or "").strip()
        if not material:
            raise ValueError("请先选择提示词素材")
        started = time.time()
        raw_progress = on_progress

        def report(value):
            # 时间兜底：慢机器上输出很长时，进度也要持续走动，避免看起来卡死
            if not raw_progress:
                return
            floor = min(88, int((time.time() - started) / 6))
            raw_progress(max(int(value), floor))

        on_progress = report if raw_progress else None

        on_progress and on_progress(20)
        model_name = ""
        if model_service is not None:
            model_name = model_service.get_default("llm") or ""

        def _rule_text(reason="（未连接大模型）"):
            return (
                f"【未调用大模型｜{reason}】\n"
                f"下面是按 skill 结构整理好的填写骨架：把「需要填写的区块」逐个写成具体描写，即可得到成品提示词。\n"
                f"点「生成成品提示词（按 Skill 规范扩写）」可由大模型自动填满。\n\n"
                f"=== 你的素材 ===\n{material}\n\n"
                f"=== 需要填写的区块（来自 skill 规范：{skill.get('keyword')}）===\n"
                f"{self._system_excerpt(skill.get('content') or '', 4000, hint=material)}"
            )

        if model_name:
            on_progress and on_progress(40)
            provider = model_service.provider_for(model_name)
            from app.services.generation_service import clean_llm_text
            spec = self._system_excerpt(skill.get("content") or "", 6000, hint=material)
            rules = f"{DELIVERABLE_RULES}\n\n=== 提示词素材 ===\n{material}\n\n请一次性输出完整的成品提示词。"
            text = ""
            try:
                text = clean_llm_text(self._generate_text(
                    provider, rules, model_name, system=spec,
                    options={"num_predict": SKILL_NUM_PREDICT, **SKILL_SAMPLING}, on_progress=on_progress,
                ))
            except Exception:
                text = ""
            text = self._clean_deliverable(text)
            if not text:
                # 空结果重试：更短的规范 + 更直接的指令
                on_progress and on_progress(65)
                try:
                    text = clean_llm_text(self._generate_text(
                        provider,
                        f"{DELIVERABLE_RULES}\n\n=== 提示词素材 ===\n{material[:2000]}\n\n"
                        f"直接输出完整的成品提示词，必须写满每一个区块。",
                        model_name,
                        system=self._system_excerpt(skill.get("content") or "", 2500, hint=material),
                        options={"num_predict": SKILL_NUM_PREDICT_RETRY, **SKILL_SAMPLING},
                        on_progress=on_progress, progress_range=(70, 93),
                    ))
                except Exception:
                    text = ""
                text = self._clean_deliverable(text)

            # 被输出上限截断 → 自动续写，直到写完或达到次数上限
            continuations = 0
            hint = ""
            while text and continuations < SKILL_MAX_CONTINUATIONS and self._is_truncated(provider, text):
                continuations += 1
                on_progress and on_progress(93)
                try:
                    piece = clean_llm_text(self._generate_text(
                        provider,
                        "下面这份成品提示词写到一半被输出上限截断了。请从断点处继续往下写完："
                        "直接接着写，不要重复已写内容、不要重新开头、不要添加任何说明，保持相同的格式与语言。\n\n"
                        f"=== 已写内容的末尾 ===\n{text[-1800:]}\n\n=== 从这里继续 ===",
                        model_name, system=spec,
                        options={"num_predict": SKILL_NUM_PREDICT, **SKILL_SAMPLING},
                        on_progress=on_progress, progress_range=(93, 94),
                    ))
                except Exception:
                    piece = ""
                piece = self._strip_overlap(text, self._clean_deliverable(piece))
                if not piece:
                    break
                text = f"{text.rstrip()}\n{piece}"

            if text:
                mode = "llm"
            else:
                # 最终兜底：规则骨架（保证结果不为空，并明确标注原因）
                text = _rule_text("模型未返回可用内容——常见原因是本地模型重复退化（输出乱码）"
                                  "或 skill 文档超出模型上下文")
                mode = "rule_fallback"
                hint = switch_model_hint(model_name, 2)
        else:
            text = _rule_text("未连接大模型")
            mode = "rule"
            continuations = 0
            hint = ""
        on_progress and on_progress(95)
        return {"mode": mode, "model": model_name, "skill_keyword": skill.get("keyword"),
                "text": text, "continuations": continuations, "hint": hint}

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
