
import json, csv, io, re
from datetime import datetime
from app.database.connection import create_connection

DEFAULT_PATTERNS = [
    ("人物摄影基础", ["subject","character","clothing","environment","camera","lighting","composition","color","style"]),
    ("电影感场景", ["subject","environment","camera","lighting","composition","color","style"]),
    ("产品商业摄影", ["product","environment","composition","camera","lighting","color","style"]),
    ("视频镜头描述", ["subject","action","environment","camera","lighting","composition","style"]),
]
DEFAULT_TEMPLATES = [
    ("人物电影摄影模板", "{subject}, {character}, {clothing}, {action}, {environment}, {camera}, {lighting}, {composition}, {color}, {style}"),
    ("商业产品摄影模板", "{product}, {environment}, {composition}, {camera}, {lighting}, {color}, {style}"),
]

class Phase2FinalizeService:
    def __init__(self, db): self.db=db

    def seed_defaults(self):
        created={"patterns":0,"templates":0}
        with create_connection(self.db) as c:
            for name,steps in DEFAULT_PATTERNS:
                if not c.execute("SELECT 1 FROM prompt_patterns WHERE name=?",(name,)).fetchone():
                    c.execute("""INSERT INTO prompt_patterns(name,description,pattern_structure,example_prompt,confidence,usage_count,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,datetime('now'),datetime('now'))""",
                    (name,"系统预置 Prompt Pattern",json.dumps(steps,ensure_ascii=False),"",1.0,0));created["patterns"]+=1
            for name,content in DEFAULT_TEMPLATES:
                if not c.execute("SELECT 1 FROM prompt_templates WHERE name=?",(name,)).fetchone():
                    p=c.execute("SELECT id FROM prompt_patterns WHERE name=? LIMIT 1",("人物摄影基础",)).fetchone()
                    c.execute("""INSERT INTO prompt_templates(name,description,pattern_id,template_content,target_model,language,version,usage_count,is_system,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
                    (name,"系统预置 Prompt Template",p["id"] if p else None,content,"","en","1.0",0,1));created["templates"]+=1
        return created

    def integrity_check(self):
        problems=[]
        with create_connection(self.db) as c:
            required={"sources","documents","images","prompts","categories","tags","prompt_tags",
                      "prompt_components","prompt_component_variants","prompt_component_relations",
                      "prompt_patterns","prompt_templates","template_components","knowledge_items",
                      "embeddings","models","generation_history","tasks","settings","schema_migrations"}
            actual={r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for t in sorted(required-actual):problems.append("缺少表:"+t)
            checks=[
                ("prompt_tags.prompt_id","SELECT pt.prompt_id FROM prompt_tags pt LEFT JOIN prompts p ON p.id=pt.prompt_id WHERE p.id IS NULL"),
                ("prompt_tags.tag_id","SELECT pt.tag_id FROM prompt_tags pt LEFT JOIN tags t ON t.id=pt.tag_id WHERE t.id IS NULL"),
                ("variants.component_id","SELECT v.component_id FROM prompt_component_variants v LEFT JOIN prompt_components c ON c.id=v.component_id WHERE c.id IS NULL"),
                ("relations.component_id","SELECT r.component_id FROM prompt_component_relations r LEFT JOIN prompt_components c ON c.id=r.component_id WHERE c.id IS NULL"),
                ("relations.related_component_id","SELECT r.related_component_id FROM prompt_component_relations r LEFT JOIN prompt_components c ON c.id=r.related_component_id WHERE c.id IS NULL"),
                ("template_components.template_id","SELECT tc.template_id FROM template_components tc LEFT JOIN prompt_templates t ON t.id=tc.template_id WHERE t.id IS NULL"),
            ]
            for name,q in checks:
                if c.execute(q).fetchone():problems.append("孤儿关联:"+name)
        return {"ok":not problems,"problems":problems}

    def export_json(self,path):
        tables=["sources","documents","images","prompts","categories","tags","prompt_tags","prompt_components",
        "prompt_component_variants","prompt_component_relations","prompt_patterns","prompt_templates",
        "template_components","knowledge_items","models","generation_history","settings"]
        data={}
        with create_connection(self.db) as c:
            for t in tables:data[t]=[dict(r) for r in c.execute(f"SELECT * FROM {t}").fetchall()]
        with open(path,"w",encoding="utf-8") as f:json.dump({"format":"PromptForge","version":1,"exported_at":datetime.now().isoformat(),"tables":data},f,ensure_ascii=False,indent=2)
        return path
