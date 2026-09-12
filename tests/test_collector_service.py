from pathlib import Path

from app.database.connection import create_connection
from app.database.migrations import migrate
from app.services.collector_service import CollectorService


def test_collect_text_and_duplicate(tmp_path):
    db = tmp_path / "test.db"
    migrate(db)
    service = CollectorService(db, tmp_path / "data")
    r1 = service.collect_text("cinematic lighting, 85mm lens", "测试Prompt")
    assert r1["status"] == "created"
    r2 = service.collect_text("cinematic lighting, 85mm lens", "另一个标题")
    assert r2["status"] == "duplicate"
    with create_connection(db) as conn:
        assert conn.execute("select count(*) from sources").fetchone()[0] == 1
        assert conn.execute("select count(*) from documents").fetchone()[0] == 1


def test_collect_text_file_and_image(tmp_path):
    db = tmp_path / "test.db"
    migrate(db)
    service = CollectorService(db, tmp_path / "data")
    txt = tmp_path / "a.txt"
    txt.write_text("电影感人像\n85mm lens", encoding="utf-8")
    assert service.collect_file(txt)["status"] == "created"
    assert service.collect_file(txt)["status"] == "duplicate"

    from PIL import Image
    image = tmp_path / "a.png"
    Image.new("RGB", (32, 24), "white").save(image)
    r = service.collect_file(image)
    assert r["status"] == "created"
    assert Path(r["file_path"]).exists()
    assert service.collect_file(image)["status"] == "duplicate"
