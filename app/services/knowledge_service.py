
from app.database.repositories import *
from app.database.connection import create_connection
from app.services.prompt_structure_service import PromptStructureService

class KnowledgeService:
    def __init__(self,db):
        self.db=db
        self.categories=CategoryRepository(db); self.sources=SourceRepository(db); self.documents=DocumentRepository(db)
        self.prompts=PromptRepository(db); self.knowledge=KnowledgeRepository(db); self.components=ComponentRepository(db)
        self.variants=ComponentVariantRepository(db); self.relations=ComponentRelationRepository(db)
        self.patterns=PatternRepository(db); self.templates=TemplateRepository(db); self.template_components=TemplateComponentRepository(db)
        self.tags=TagRepository(db); self.prompt_tags=PromptTagRepository(db)
        self.structure=PromptStructureService()

    def category_tree(self):
        rows=self.categories.list_all(); by_parent={}
        for r in rows:by_parent.setdefault(r.get("parent_id"),[]).append(r)
        def build(p):return [{**r,"children":build(r["id"])} for r in by_parent.get(p,[])]
        return build(None)

    def dashboard_counts(self):
        return {k:getattr(self,k).count() for k in ("sources","documents","prompts","knowledge","components","templates")}

    def search_prompts(self,keyword="",page=1,page_size=50):return self.prompts.search(keyword,page,page_size)
    def create_prompt(self,data):return self.prompts.create(data)
    def update_prompt(self,i,data):return self.prompts.update(i,data)
    def delete_prompt(self,i):return self.prompts.delete(i)

    def list_knowledge(self,category_id=None,keyword="",page=1,page_size=50):return self.knowledge.search(keyword,category_id,page,page_size)
    def create_knowledge(self,data):
        data={"source_type":"manual",**data};return self.knowledge.create(data)
    def update_knowledge(self,i,data):return self.knowledge.update(i,data)
    def delete_knowledge(self,i):return self.knowledge.delete(i)

    def create_source(self,d):return self.sources.create(d)
    def update_source(self,i,d):return self.sources.update(i,d)
    def delete_source(self,i):return self.sources.delete(i)
    def create_category(self,d):return self.categories.create(d)
    def update_category(self,i,d):return self.categories.update(i,d)
    def delete_category(self,i):return self.categories.delete(i)

    def component_variants(self,component_id):
        with create_connection(self.db) as c:return [dict(r) for r in c.execute("SELECT * FROM prompt_component_variants WHERE component_id=? ORDER BY usage_count DESC,id",(component_id,)).fetchall()]

    def prompt_source_trace(self,prompt_id):
        p=self.prompts.get(prompt_id)
        if not p:return None
        s=self.sources.get(p.get("source_id")) if p.get("source_id") else None; img=None
        if p.get("image_id"):
            with create_connection(self.db) as c:
                r=c.execute("SELECT * FROM images WHERE id=?",(p["image_id"],)).fetchone();img=dict(r) if r else None
        return {"prompt":p,"source":s,"image":img}

    def set_prompt_tags(self,prompt_id,tag_ids):
        with create_connection(self.db) as c:
            c.execute("DELETE FROM prompt_tags WHERE prompt_id=?",(prompt_id,))
            for tid in tag_ids:c.execute("INSERT INTO prompt_tags(prompt_id,tag_id) VALUES(?,?)",(prompt_id,tid))

    def prompt_tags_for(self,prompt_id):
        with create_connection(self.db) as c:return [dict(r) for r in c.execute("SELECT t.* FROM tags t JOIN prompt_tags pt ON pt.tag_id=t.id WHERE pt.prompt_id=? ORDER BY t.name",(prompt_id,)).fetchall()]

    def build_prompt_structure(self,prompt_text,components=None):
        s=self.structure.build_structure(prompt_text,components);return {"structure":s,"dna":self.structure.dna(s)}
