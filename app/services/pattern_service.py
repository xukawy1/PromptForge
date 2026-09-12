
import json
from app.database.repositories import PatternRepository, TemplateRepository, TemplateComponentRepository
from app.database.connection import create_connection
class PatternService:
    def __init__(self,db):
        self.db=db;self.patterns=PatternRepository(db);self.templates=TemplateRepository(db);self.template_components=TemplateComponentRepository(db)
    def create_pattern(self,name,steps,description="",category_id=None,example_prompt=""):
        return self.patterns.create({"name":name,"description":description,"category_id":category_id,"pattern_structure":json.dumps(steps,ensure_ascii=False),"example_prompt":example_prompt,"confidence":0,"usage_count":0})
    def pattern_steps(self,row):
        try:return json.loads(row.get("pattern_structure") or "[]")
        except:return []
    def create_template(self,data,variables):
        tid=self.templates.create(data)
        for i,v in enumerate(variables):
            self.template_components.create({"template_id":tid,"variable_name":v["variable_name"],"display_name":v.get("display_name",v["variable_name"]),"category_id":v.get("category_id"),"required":1 if v.get("required") else 0,"default_value":v.get("default_value",""),"sort_order":i})
        return tid
    def variables(self,template_id):
        with create_connection(self.db) as c:return [dict(r) for r in c.execute("SELECT * FROM template_components WHERE template_id=? ORDER BY sort_order,id",(template_id,)).fetchall()]
