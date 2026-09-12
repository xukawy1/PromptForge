from pathlib import Path

from app.services.collector_service import CollectorService


def test_text_metadata():
    meta = CollectorService.build_text_metadata("# 电影感人像\ncinematic lighting, 85mm lens", "")
    assert meta["title"] == "电影感人像"
    assert meta["language"] == "zh-en"
    assert meta["content_type"] == "markdown"
    assert meta["word_count"] > 0
    assert meta["char_count"] > 0


def test_collect_text_auto_title_and_metadata(tmp_path):
    svc = CollectorService(tmp_path / "db.sqlite", tmp_path / "data")
    from app.database.migrations import migrate
    migrate(tmp_path / "db.sqlite")
    text = "# Prompt技巧\ncinematic lighting, 85mm lens"
    result = svc.collect_text(text)
    assert result["status"] == "created"
    assert result["metadata"]["title"] == "Prompt技巧"
    assert result["metadata"]["content_type"] == "markdown"


def test_collect_text_duplicate(tmp_path):
    db = tmp_path / "db.sqlite"
    data = tmp_path / "data"
    from app.database.migrations import migrate
    migrate(db)
    svc = CollectorService(db, data)
    text = "同一份知识资料"
    assert svc.collect_text(text)["status"] == "created"
    second = svc.collect_text(text)
    assert second["status"] == "duplicate"
