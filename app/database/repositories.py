
from datetime import datetime
from app.database.connection import create_connection

def _now():
    return datetime.now().isoformat(timespec="seconds")

class BaseRepository:
    table = None
    allowed = set()
    def __init__(self, db_path): self.db_path = db_path
    def _conn(self): return create_connection(self.db_path)
    def count(self, where="", params=()):
        with self._conn() as c:
            q=f"SELECT COUNT(*) FROM {self.table}" + (f" WHERE {where}" if where else "")
            return c.execute(q, params).fetchone()[0]
    def list_all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT * FROM {self.table} ORDER BY id").fetchall()]
    def get(self, row_id):
        with self._conn() as c:
            r=c.execute(f"SELECT * FROM {self.table} WHERE id=?", (row_id,)).fetchone()
            return dict(r) if r else None
    def create(self, data):
        data={k:v for k,v in data.items() if k in self.allowed}
        cols=", ".join(data); marks=", ".join("?" for _ in data)
        with self._conn() as c:
            cur=c.execute(f"INSERT INTO {self.table} ({cols}) VALUES ({marks})", tuple(data.values()))
            return cur.lastrowid
    def update(self, row_id, data):
        data={k:v for k,v in data.items() if k in self.allowed and k not in {"created_at"}}
        if not data:return False
        if "updated_at" in self.allowed:data["updated_at"]=_now()
        sets=", ".join(f"{k}=?" for k in data)
        with self._conn() as c:
            cur=c.execute(f"UPDATE {self.table} SET {sets} WHERE id=?", (*data.values(),row_id))
            return cur.rowcount>0
    def delete(self,row_id):
        with self._conn() as c:
            cur=c.execute(f"DELETE FROM {self.table} WHERE id=?",(row_id,))
            return cur.rowcount>0

class CategoryRepository(BaseRepository):
    table="categories"; allowed={"parent_id","name","description","sort_order","created_at","updated_at"}
    def list_all(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM categories ORDER BY COALESCE(parent_id,0),sort_order,id").fetchall()]

class SourceRepository(BaseRepository):
    table="sources"; allowed={"title","url","source_type","author","publish_time","description","content_hash","status","created_at","updated_at"}

class DocumentRepository(BaseRepository):
    table="documents"; allowed={"source_id","title","content","content_hash","language","word_count","summary","raw_html_path","created_at","updated_at"}

class PromptRepository(BaseRepository):
    table="prompts"; allowed={"source_id","image_id","title","prompt_text","negative_prompt","prompt_type","target_model","language","content_hash","analysis_result","analysis_status","created_at","updated_at"}
    def search(self,keyword="",page=1,page_size=50):
        keyword=(keyword or "").strip(); offset=max(0,(page-1)*page_size)
        with self._conn() as c:
            if keyword:
                like=f"%{keyword}%"; where="title LIKE ? OR prompt_text LIKE ? OR negative_prompt LIKE ?"
                rows=c.execute(f"SELECT * FROM prompts WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",(like,like,like,page_size,offset)).fetchall()
                total=c.execute(f"SELECT COUNT(*) FROM prompts WHERE {where}",(like,like,like)).fetchone()[0]
            else:
                rows=c.execute("SELECT * FROM prompts ORDER BY updated_at DESC LIMIT ? OFFSET ?",(page_size,offset)).fetchall()
                total=c.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        return {"items":[dict(r) for r in rows],"total":total,"page":page,"page_size":page_size}

class TagRepository(BaseRepository):
    table="tags"; allowed={"name","description","created_at","updated_at"}

class PromptTagRepository(BaseRepository):
    table="prompt_tags"; allowed={"prompt_id","tag_id"}

class ComponentRepository(BaseRepository):
    table="prompt_components"; allowed={"category_id","canonical_name","name_zh","name_en","description","usage_context","component_type","confidence","usage_count","is_favorite","created_at","updated_at"}

class ComponentVariantRepository(BaseRepository):
    table="prompt_component_variants"; allowed={"component_id","variant_text","language","style","source_prompt_id","confidence","usage_count","created_at"}

class ComponentRelationRepository(BaseRepository):
    table="prompt_component_relations"; allowed={"component_id","related_component_id","relation_type","weight","created_at"}

class PatternRepository(BaseRepository):
    table="prompt_patterns"; allowed={"name","description","category_id","pattern_structure","example_prompt","confidence","usage_count","created_at","updated_at"}

class TemplateRepository(BaseRepository):
    table="prompt_templates"; allowed={"name","description","category_id","pattern_id","template_content","target_model","language","version","usage_count","is_system","created_at","updated_at"}

class TemplateComponentRepository(BaseRepository):
    table="template_components"; allowed={"template_id","variable_name","display_name","category_id","required","default_value","sort_order"}

class KnowledgeRepository(BaseRepository):
    table="knowledge_items"; allowed={"source_type","source_id","title","content","summary","category_id","knowledge_type","confidence","created_at","updated_at"}
    def search(self,keyword="",category_id=None,page=1,page_size=50):
        clauses=[];params=[]
        if keyword:
            like=f"%{keyword}%"; clauses.append("(title LIKE ? OR content LIKE ? OR summary LIKE ?)");params += [like]*3
        if category_id:clauses.append("category_id=?");params.append(category_id)
        where=(" WHERE "+" AND ".join(clauses)) if clauses else "";offset=max(0,(page-1)*page_size)
        with self._conn() as c:
            rows=c.execute(f"SELECT * FROM knowledge_items{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",(*params,page_size,offset)).fetchall()
            total=c.execute(f"SELECT COUNT(*) FROM knowledge_items{where}",tuple(params)).fetchone()[0]
        return {"items":[dict(r) for r in rows],"total":total,"page":page,"page_size":page_size}

class EmbeddingRepository(BaseRepository):
    table="embeddings"; allowed={"object_type","object_id","content_hash","model_name","vector_data","dimensions","created_at"}

class ModelRepository(BaseRepository):
    table="models"; allowed={"name","provider","model_type","model_identifier","local_path","endpoint","status","is_default","parameters","created_at","updated_at"}

class GenerationHistoryRepository(BaseRepository):
    table="generation_history"; allowed={"user_input","prompt_result","negative_prompt","model_id","template_id","retrieved_context","parameters","created_at"}

class TaskRepository(BaseRepository):
    table="tasks"; allowed={"id","task_type","status","progress","input_data","result_data","error_message","retry_count","created_at","started_at","finished_at"}

class SettingsRepository(BaseRepository):
    table="settings"; allowed={"key","value","value_type","updated_at"}
