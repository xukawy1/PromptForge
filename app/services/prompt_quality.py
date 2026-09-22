"""提示词成品质量层：软件里所有"让模型写提示词"的地方都走这里。

覆盖范围：Skill 工坊扩写、采集中心拆分/综合提示词规整/单条扩写、Prompt 生成。
统一保证三件事：
1. 产出的是【成品提示词】——规范只用来指导"怎么写"，绝不允许把规范原文、字段表、示例搬给用户；
2. 输出为空或被识别为退化乱码（同一字符大量重复）时自动重试，而不是把垃圾当结果；
3. 同一模型连续失败到阈值时，给出"换模型 / 改用 API"的明确提示，而不是静默糊弄过去。
"""
from __future__ import annotations

import re
from collections import Counter

# 成品铁律：所有提示词生成任务共用的最高约束
DELIVERABLE_RULES = """你是资深提示词工程师。你的唯一任务是产出一份【成品提示词】：用户拿到后可以直接复制到目标模型里使用，不需要再做任何编辑。

铁律（全部必须遵守）：
1. 只输出成品本身。不要解释、不要前言或结束语（如"以下是……""希望对你有帮助"），不要复述或输出规范/模板原文。
2. 规范、模板、参考资料里的说明性内容——规则条目、示例表格、字段清单、写作要求、"示例："、来源文件名——一律不得出现在结果里。它们只是"该怎么写"的依据：读懂之后，直接把"写好的结果"写出来。
3. 规范要求的每一个区块/字段都必须填成具体内容：不得保留占位符（<...>、{}、XXX），不得写"待填""同上""略""……"，也不得只把字段名抄一行就算完成，必须写出该字段应有的具体描写。
4. 规范提供多种模板/风格/分支时：判断素材属于哪一种，只输出这一种，不要并列罗列多个模板。
5. 规范要求的成品结构（分区标题、顺序编号、正向/负向分段等）要保留，但用成品内容填充。
6. 语言以规范对"成品"的要求为准（如规范要求成品用英文，正文就用英文；规范允许的中文标签可保留）。
7. 宁可写长写全，也不要提前收尾：每个区块都要写完，不要在结尾留下未完成的段落。
8. 素材里的信息必须优先保留、不得违背；素材未提供的部分按规范自动补全为合理内容。"""

# 同一模型反复失败时给用户的建议（换模型 / 改用 API）
MODEL_SWITCH_HINT = (
    "当前模型「{model}」已连续 {attempts} 次没能写出可用内容（返回空或重复乱码）。\n"
    "建议任选一种方式后重试：\n"
    "· 在「模型中心」换用更稳的本地模型（推荐 qwen3.8 系列），或把默认 LLM 改成别的模型；\n"
    "· 在「模型中心」添加 API 供应商（GPT / DeepSeek / GLM / Kimi / 通义）并设为当前供应商——"
    "API 模型写长成品更稳，也不吃本机显存。"
)

# 退化判定：单一字符或三连串占比过高
DEGENERATE_CHAR_RATIO = 0.22
DEGENERATE_GRAM_RATIO = 0.3


def looks_degenerate(text: str) -> bool:
    """识别模型退化输出（同一字符或三连串大量重复的乱码）。"""
    t = re.sub(r"\s+", "", text or "")
    if len(t) < 80:
        return False
    counts = Counter(t)
    _, top = counts.most_common(1)[0]
    if top / len(t) > DEGENERATE_CHAR_RATIO:
        return True
    grams = Counter(t[i:i + 3] for i in range(len(t) - 2))
    _, n = grams.most_common(1)[0]
    return n > 20 and (n * 3) / len(t) > DEGENERATE_GRAM_RATIO


# 泄漏的规范痕迹 / 客套开场白
_META_LINE_PATTERNS = (
    re.compile(r"^#*\s*来源文件[:：]"),
    re.compile(r"^={2,}\s*Skill 格式说明"),
    re.compile(r"^={2,}\s*提示词素材\s*={2,}"),
    re.compile(r"^={2,}\s*要扩写的提示词素材\s*={2,}"),
    re.compile(r"^[（(]\s*(以上|上述)为\s*skill"),
    re.compile(r"^[（(]未连接大模型"),
    re.compile(r"^[（(]模型未返回内容"),
)
_PREAMBLE_PATTERNS = (
    re.compile(r"^(以下|下面)(是|为)"),
    re.compile(r"^好的[，,。:：]?"),
    re.compile(r"^根据(你的|您的|上述)"),
    re.compile(r"^(here('| i)s|below is|sure[,，]|certainly[,，])", re.I),
)


def clean_deliverable(text: str) -> str:
    """清掉泄漏的规范痕迹与客套开场白；退化乱码直接判为无效（返回空串以便触发重试）。"""
    text = (text or "").strip()
    if not text:
        return ""
    if looks_degenerate(text):
        return ""
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    kept = [line for line in text.splitlines()
            if not any(p.search(line.strip()) for p in _META_LINE_PATTERNS)]
    text = "\n".join(kept).strip()
    head, sep, rest = text.partition("\n\n")
    if sep and rest.strip() and len(head) <= 220 and any(p.search(head.strip()) for p in _PREAMBLE_PATTERNS):
        text = rest.strip()
    return text


def switch_model_hint(model: str, attempts: int) -> str:
    return MODEL_SWITCH_HINT.format(model=model or "（未指定）", attempts=attempts)


def is_model_switch_hint(message) -> bool:
    """判断一段错误/提示文本是不是"该换模型了"的建议（UI 据此弹出跳转模型中心的对话框）。"""
    text = str(message or "")
    return ("换用更稳的本地模型" in text) or ("添加 API 供应商" in text)


def _clean_llm(raw: str) -> str:
    from app.services.generation_service import clean_llm_text
    return clean_llm_text(raw)


def stream_generate(provider, prompt, model, *, system=None, options=None,
                    on_chunk=None, on_progress=None, progress_range=None, stream_chars=9000,
                    think=False) -> str:
    """统一的生成入口：能用流式就走流式（长成品不会撞上单次读取超时，并可回传进度）。

    think=False（默认）：提示词成品类任务关掉思考过程——思考会吃掉输出额度，
    思考型本地模型（qwen3.8 等）思考占满后正文会是空的；不支持的 provider 自动忽略。
    """
    extra = {"think": think} if getattr(provider, "SUPPORTS_THINK", False) else {}
    stream = getattr(provider, "generate_stream", None)
    if callable(stream):
        low, high = progress_range or (0, 0)
        has_range = bool(progress_range)

        def _chunk(full, piece):
            if on_chunk:
                on_chunk(full, piece)
            if on_progress and has_range:
                ratio = min(1.0, len(full) / max(1, stream_chars))
                on_progress(round(low + (high - low) * ratio))

        try:
            return stream(prompt, model, system=system, options=options, on_chunk=_chunk, **extra)
        except TypeError:
            pass  # 该 provider 的流式签名不同 → 退回非流式
    return provider.generate(prompt, model, system=system, options=options, **extra)


def _scaled_options(options):
    """输出额度放大（最多 8192）：思考型模型把额度花在 reasoning 上时，重试需要更大预算才出正文。"""
    if not options:
        return None
    out = dict(options)
    for key in ("max_tokens", "num_predict"):
        if key in out:
            out[key] = min(8192, max(1024, int(out[key]) * 3))
    return out


def generate_deliverable(provider, prompt, model, *, system=None, options=None, on_chunk=None,
                         on_progress=None, progress_range=(45, 90), attempts=2,
                         retry_prompt=None, retry_options=None) -> dict:
    """生成并校验成品：空/退化 → 换更短的指令重试 → 仍失败则返回换模型提示。

    返回 {"text", "attempts", "failed", "hint"}；text 为空时 failed=True，hint 是给用户看的建议。
    """
    attempts = max(1, int(attempts))
    used = 0
    for i in range(attempts):
        used = i + 1
        use_prompt = prompt if i == 0 else (retry_prompt or prompt)
        use_options = options if i == 0 else (retry_options or options)
        if i > 0 and not retry_options and getattr(provider, "last_reasoning", ""):
            # 上一轮返回空但模型确实"想了"（reasoning 有内容）→ 判定为额度被思考吃掉，放大预算重试
            use_options = _scaled_options(options)
        try:
            raw = stream_generate(provider, use_prompt, model, system=system, options=use_options,
                                  on_chunk=on_chunk if i == 0 else None,
                                  on_progress=on_progress, progress_range=progress_range)
        except Exception:
            raw = ""
        text = clean_deliverable(_clean_llm(raw)) if raw else ""
        if text:
            return {"text": text, "attempts": used, "failed": False, "hint": ""}
    hint = switch_model_hint(model, used)
    if getattr(provider, "last_reasoning", ""):
        hint += ("\n（提示：该模型把输出额度用在了「思考」上，正文为空。"
                 "建议换用非思考型模型，或在模型中心换一个更快的模型。）")
    return {"text": "", "attempts": used, "failed": True, "hint": hint}
