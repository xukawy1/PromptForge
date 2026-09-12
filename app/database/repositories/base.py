from app.database.connection import create_connection

class BaseRepository:
    table = ""
    fields = ()
    order_by = "id DESC"

    def __init__(self, db_path):
        self.db_path = db_path

    def create(self, data: dict):
        cols = [c for c in self.fields if c in data]
        if not cols:
            raise ValueError(f"{self.table} 没有可写入字段")
        values = [data[c] for c in cols]
        sql = f"INSERT INTO {self.table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with create_connection(self.db_path) as conn:
            return conn.execute(sql, values).lastrowid

    def get(self, item_id):
        with create_connection(self.db_path) as conn:
            row = conn.execute(f"SELECT * FROM {self.table} WHERE id = ?", (item_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit=100, offset=0, where="", params=(), order_by=None):
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        order = order_by or self.order_by
        sql = f"SELECT * FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
        with create_connection(self.db_path) as conn:
            rows = conn.execute(sql, tuple(params) + (limit, offset)).fetchall()
            return [dict(r) for r in rows]

    def count(self, where="", params=()):
        sql = f"SELECT COUNT(*) AS n FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        with create_connection(self.db_path) as conn:
            return conn.execute(sql, tuple(params)).fetchone()["n"]

    def list_all(self):
        with create_connection(self.db_path) as conn:
            rows = conn.execute(f"SELECT * FROM {self.table} ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def update(self, item_id, data: dict):
        cols = [c for c in self.fields if c in data]
        if not cols:
            return False
        assignments = ", ".join(f"{c} = ?" for c in cols)
        values = [data[c] for c in cols] + [item_id]
        with create_connection(self.db_path) as conn:
            cur = conn.execute(f"UPDATE {self.table} SET {assignments} WHERE id = ?", values)
            return cur.rowcount > 0

    def delete(self, item_id):
        with create_connection(self.db_path) as conn:
            cur = conn.execute(f"DELETE FROM {self.table} WHERE id = ?", (item_id,))
            return cur.rowcount > 0

    def search(self, keyword, fields, limit=100, offset=0):
        keyword = (keyword or "").strip()
        if not keyword:
            return self.list(limit, offset)
        safe_fields = [f for f in fields if f in self.fields]
        if not safe_fields:
            return []
        where = " OR ".join(f"{f} LIKE ?" for f in safe_fields)
        params = tuple(f"%{keyword}%" for _ in safe_fields)
        return self.list(limit, offset, where, params)
