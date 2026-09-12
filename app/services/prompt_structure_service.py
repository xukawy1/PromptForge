
import hashlib, json, re
from collections import Counter

DEFAULT_SLOTS = [
    ("subject","主体"),("character","人物"),("clothing","服装"),
    ("action","动作"),("environment","环境"),("camera","镜头"),
    ("lens","焦段"),("lighting","光线"),("composition","构图"),
    ("color","色彩"),("style","风格"),("quality","质量")
]

class PromptStructureService:
    """不依赖 LLM 的确定性基础结构层；未来 AI 分析结果可直接写入同一协议。"""
    def tokenize(self, text):
        return [x.strip() for x in re.split(r"[,，\n;；]+", text or "") if x.strip()]

    def build_structure(self, prompt_text, components=None):
        components = components or []
        groups = {k: [] for k,_ in DEFAULT_SLOTS}
        for c in components:
            category=(c.get("category") or c.get("category_key") or "").lower()
            name=c.get("canonical_name") or c.get("name") or c.get("text") or ""
            if category in groups and name: groups[category].append(name)
        if not any(groups.values()):
            groups["subject"] = self.tokenize(prompt_text)[:1]
        return {"version":1,"slots":[{"key":k,"name_zh":zh,"items":groups[k]} for k,zh in DEFAULT_SLOTS]}

    def dna(self, structure):
        keys=[x["key"] for x in structure.get("slots",[]) if x.get("items")]
        signature=">".join(keys)
        return {"version":1,"signature":signature,
                "hash":hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16],
                "slot_count":len(keys)}

    def compare(self, a, b):
        sa=set(x["key"] for x in a.get("slots",[]) if x.get("items"))
        sb=set(x["key"] for x in b.get("slots",[]) if x.get("items"))
        union=sa|sb; inter=sa&sb
        return {"common_slots":sorted(inter),"only_a":sorted(sa-sb),"only_b":sorted(sb),
                "similarity":round(len(inter)/len(union),4) if union else 1.0}
