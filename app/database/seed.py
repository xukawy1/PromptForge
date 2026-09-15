from app.database.connection import create_connection

DEFAULT_CATEGORIES = [
    (None, "人物", 10), (None, "场景", 20), (None, "摄影", 30), (None, "镜头语言", 40),
    (None, "光线", 50), (None, "构图", 60), (None, "色彩", 70), (None, "风格", 80),
    (None, "视频", 90), (None, "声音", 100), (None, "质量", 110), (None, "其他", 999),
]

def seed_defaults(db_path):
    with create_connection(db_path) as conn:
        for parent_id, name, sort_order in DEFAULT_CATEGORIES:
            # SQLite 的 UNIQUE(parent_id,name) 对 NULL 父级不生效，必须显式判重，否则每次启动都会追加副本。
            exists = conn.execute(
                "SELECT 1 FROM categories WHERE name=? AND parent_id IS NULL", (name,)
            ).fetchone()
            if not exists:
                conn.execute("INSERT INTO categories(parent_id,name,sort_order) VALUES(?,?,?)", (parent_id, name, sort_order))
        defaults = {
            "app_initialized": ("1", "bool"),
            "theme_mode": ("system", "string"),
            "accent_color": ("blue", "string"),
        }
        for key, (value, value_type) in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value,value_type) VALUES(?,?,?)", (key, value, value_type))
