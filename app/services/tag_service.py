
from app.database.repositories import TagRepository, PromptTagRepository
from app.database.connection import create_connection

class TagService:
    def __init__(self, db):
        self.db=db; self.tags=TagRepository(db); self.prompt_tags=PromptTagRepository(db)
    def list(self, keyword=""):
        rows=self.tags.list_all()
        k=(keyword or "").strip().lower()
        return [x for x in rows if not k or k in (x.get("name") or "").lower()]
    def create(self,name,description=""):
        name=name.strip()
        if not name:return None
        for x in self.tags.list_all():
            if x.get("name","").strip().lower()==name.lower():return x["id"]
        return self.tags.create({"name":name,"description":description})
    def delete(self,tag_id):return self.tags.delete(tag_id)
    def tags_for_prompt(self,prompt_id):
        with create_connection(self.db) as c:
            return [dict(r) for r in c.execute(
                "SELECT t.* FROM tags t JOIN prompt_tags pt ON pt.tag_id=t.id WHERE pt.prompt_id=? ORDER BY t.name",(prompt_id,)).fetchall()]
    def set_prompt_tags(self,prompt_id,tag_ids):
        with create_connection(self.db) as c:
            c.execute("DELETE FROM prompt_tags WHERE prompt_id=?",(prompt_id,))
            for tid in tag_ids:c.execute("INSERT OR IGNORE INTO prompt_tags(prompt_id,tag_id) VALUES(?,?)",(prompt_id,tid))
