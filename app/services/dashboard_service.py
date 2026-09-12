from app.database.connection import create_connection

class DashboardService:
    def __init__(self, db_path):
        self.db_path = db_path

    def stats(self):
        tables = ["sources", "documents", "images", "prompts", "prompt_components", "prompt_templates", "knowledge_items", "generation_history"]
        result = {}
        with create_connection(self.db_path) as conn:
            for table in tables:
                result[table] = conn.execute(f"SELECT COUNT(*) n FROM {table}").fetchone()["n"]
            result["pending_tasks"] = conn.execute("SELECT COUNT(*) n FROM tasks WHERE status IN ('pending','running')").fetchone()["n"]
        return result

    def recent_prompts(self, limit=5):
        with create_connection(self.db_path) as conn:
            rows = conn.execute("SELECT id,title,prompt_text,created_at FROM prompts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def recent_sources(self, limit=5):
        with create_connection(self.db_path) as conn:
            rows = conn.execute("SELECT id,title,source_type,status,created_at FROM sources ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]
