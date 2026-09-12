from .base import BaseRepository

class SourceRepository(BaseRepository):
    table="sources"; fields=("title","url","source_type","author","publish_time","description","content_hash","status")
    def search_text(self, keyword, limit=100, offset=0): return self.search(keyword,("title","url","author","description"),limit,offset)

class DocumentRepository(BaseRepository):
    table="documents"; fields=("source_id","title","content","content_hash","language","word_count","summary","raw_html_path")
    def search_text(self, keyword, limit=100, offset=0): return self.search(keyword,("title","content","summary"),limit,offset)

class ImageRepository(BaseRepository):
    table="images"; fields=("source_id","document_id","file_path","original_url","file_hash","width","height","format","metadata","ocr_text","vision_result","analysis_status")

class PromptRepository(BaseRepository):
    table="prompts"; fields=("source_id","image_id","title","prompt_text","negative_prompt","prompt_type","target_model","language","content_hash","analysis_result","analysis_status")
    def search_text(self, keyword, limit=100, offset=0):
        """按关键词检索 Prompt，返回列表（供简单搜索场景使用）。"""
        from app.database.connection import create_connection
        keyword = (keyword or "").strip()
        with create_connection(self.db_path) as c:
            if keyword:
                like = f"%{keyword}%"
                where = "title LIKE ? OR prompt_text LIKE ? OR negative_prompt LIKE ? OR target_model LIKE ?"
                rows = c.execute(f"SELECT * FROM prompts WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (like, like, like, like, limit, offset)).fetchall()
            else:
                rows = c.execute("SELECT * FROM prompts ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(r) for r in rows]
    def search(self, keyword="", page=1, page_size=50):
        """分页检索 Prompt，返回 {"items","total","page","page_size"}。"""
        from app.database.connection import create_connection
        keyword = (keyword or "").strip()
        offset = max(0, (page-1)*page_size)
        with create_connection(self.db_path) as c:
            if keyword:
                like = f"%{keyword}%"
                where = "title LIKE ? OR prompt_text LIKE ? OR negative_prompt LIKE ?"
                rows = c.execute(f"SELECT * FROM prompts WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (like, like, like, page_size, offset)).fetchall()
                total = c.execute(f"SELECT COUNT(*) FROM prompts WHERE {where}", (like, like, like)).fetchone()[0]
            else:
                rows = c.execute("SELECT * FROM prompts ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
                total = c.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}

class CategoryRepository(BaseRepository):
    table="categories"; fields=("parent_id","name","description","sort_order"); order_by="sort_order ASC, id ASC"

class TagRepository(BaseRepository):
    table="tags"; fields=("name","description")

class PromptTagRepository(BaseRepository):
    table="prompt_tags"; fields=("prompt_id","tag_id"); order_by="prompt_id ASC, tag_id ASC"

class ComponentRepository(BaseRepository):
    table="prompt_components"; fields=("category_id","canonical_name","name_zh","name_en","description","usage_context","component_type","confidence","usage_count","is_favorite")
    def search_text(self, keyword, limit=100, offset=0): return self.search(keyword,("canonical_name","name_zh","name_en","description","usage_context"),limit,offset)

class ComponentVariantRepository(BaseRepository):
    table="prompt_component_variants"; fields=("component_id","variant_text","language","style","source_prompt_id","confidence","usage_count")

class ComponentRelationRepository(BaseRepository):
    table="prompt_component_relations"; fields=("component_id","related_component_id","relation_type","weight")

class PatternRepository(BaseRepository):
    table="prompt_patterns"; fields=("name","description","category_id","pattern_structure","example_prompt","confidence","usage_count")

class TemplateRepository(BaseRepository):
    table="prompt_templates"; fields=("name","description","category_id","pattern_id","template_content","target_model","language","version","usage_count","is_system")

class TemplateComponentRepository(BaseRepository):
    table="template_components"; fields=("template_id","variable_name","display_name","category_id","required","default_value","sort_order"); order_by="sort_order ASC, id ASC"

class KnowledgeRepository(BaseRepository):
    table="knowledge_items"; fields=("source_type","source_id","title","content","summary","category_id","knowledge_type","confidence")
    def search_text(self, keyword, limit=100, offset=0): return self.search(keyword,("title","content","summary","knowledge_type"),limit,offset)
    def search_category(self, category_id, keyword="", limit=100, offset=0):
        if keyword:
            like=f"%{keyword}%"; where="category_id=? AND (title LIKE ? OR content LIKE ? OR summary LIKE ?)"; params=(category_id,like,like,like)
        else: where="category_id=?"; params=(category_id,)
        return self.list(limit,offset,where,params)
    def search(self, keyword="", category_id=None, page=1, page_size=50):
        """按关键词与分类过滤知识条目，返回列表。"""
        from app.database.connection import create_connection
        keyword = (keyword or "").strip()
        where, params = [], []
        if keyword:
            like = f"%{keyword}%"; where.append("(title LIKE ? OR content LIKE ? OR summary LIKE ?)"); params += [like]*3
        if category_id:
            where.append("category_id=?"); params.append(category_id)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        offset = max(0, (page-1)*page_size)
        with create_connection(self.db_path) as c:
            rows = c.execute(f"SELECT * FROM knowledge_items{clause} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, page_size, offset)).fetchall()
        return [dict(r) for r in rows]

class ModelRepository(BaseRepository):
    table="models"; fields=("name","provider","model_type","model_identifier","local_path","endpoint","status","is_default","parameters")
class GenerationHistoryRepository(BaseRepository):
    table="generation_history"; fields=("user_input","prompt_result","negative_prompt","model_id","template_id","retrieved_context","parameters")
class TaskRepository(BaseRepository):
    table="tasks"; fields=("id","task_type","status","progress","input_data","result_data","error_message","retry_count","created_at","started_at","finished_at")
    def get_by_status(self,status,limit=100): return self.list(limit=limit,where="status=?",params=(status,),order_by="created_at DESC")
class SettingsRepository(BaseRepository):
    table="settings"; fields=("key","value","value_type")
    def get_value(self,key,default=None):
        from app.database.connection import create_connection
        with create_connection(self.db_path) as c:
            r=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); return r["value"] if r else default
    def set_value(self,key,value,value_type="string"):
        from app.database.connection import create_connection
        with create_connection(self.db_path) as c:
            c.execute("INSERT INTO settings(key,value,value_type) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,value_type=excluded.value_type,updated_at=CURRENT_TIMESTAMP",(key,str(value),value_type))


class SkillRepository(BaseRepository):
    table="skills"; fields=("keyword","name","description","content","source_path","file_count")
