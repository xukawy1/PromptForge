import sqlite3
from pathlib import Path
from app.database.connection import create_connection
from app.database.migrations import migrate
from app.database.seed import seed_defaults
from app.database.repositories import SourceRepository

def test_migration_and_seed(tmp_path: Path):
    db = tmp_path / "test.db"
    migrate(db)
    seed_defaults(db)
    with create_connection(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "sources" in tables
        assert "prompt_components" in tables
        assert "generation_history" in tables
        assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] >= 10

def test_repository_crud(tmp_path: Path):
    db = tmp_path / "test.db"
    migrate(db)
    repo = SourceRepository(db)
    item_id = repo.create({"title":"测试来源", "source_type":"manual"})
    assert repo.get(item_id)["title"] == "测试来源"
    assert repo.update(item_id, {"title":"更新来源"})
    assert repo.get(item_id)["title"] == "更新来源"
    assert repo.delete(item_id)
    assert repo.get(item_id) is None
