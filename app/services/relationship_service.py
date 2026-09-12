
from app.database.connection import create_connection
class RelationshipService:
    def __init__(self,db):self.db=db
    def link_prompt_component(self,prompt_id,component_id,variant_text=None):
        # Existing schema stores source_prompt_id on variants; keep relation backward-compatible.
        if variant_text is not None:
            with create_connection(self.db) as c:
                row=c.execute("SELECT id FROM prompt_component_variants WHERE component_id=? AND variant_text=?",(component_id,variant_text)).fetchone()
                if row:return row["id"]
        return None
    def component_relations(self,component_id):
        with create_connection(self.db) as c:
            return [dict(r) for r in c.execute("""SELECT r.*,c.canonical_name,c.name_zh
                FROM prompt_component_relations r JOIN prompt_components c ON c.id=r.related_component_id
                WHERE r.component_id=? ORDER BY r.weight DESC,r.id""",(component_id,)).fetchall()]
    def add_component_relation(self,a,b,relation_type="related",weight=1.0):
        with create_connection(self.db) as c:
            cur=c.execute("""INSERT INTO prompt_component_relations
                (component_id,related_component_id,relation_type,weight) VALUES(?,?,?,?)""",(a,b,relation_type,weight))
            return cur.lastrowid
