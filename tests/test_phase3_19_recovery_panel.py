from pathlib import Path
from app.database.migrations import migrate
from app.services.task_service import TaskService


def make_service(tmp_path: Path) -> TaskService:
    db = tmp_path / "recovery.db"
    migrate(db)
    return TaskService(db)


def collection_payload(operation="网页采集", version=1):
    return {
        "label": operation,
        "args": ["https://example.com", ""],
        "execution_plan": {"kind": "collector", "operation": operation, "version": version},
    }


def test_interrupted_tasks_are_marked_and_listed(tmp_path: Path):
    service = make_service(tmp_path)
    service.create("run-1", "collection.网页采集", collection_payload())
    service.update("run-1", status="running", progress=40, started=True)
    recovered = service.recover_interrupted_tasks()
    assert recovered == ["run-1"]
    rows = service.list_interrupted_tasks()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert TaskService.INTERRUPTED_MESSAGE in rows[0]["error_message"]


def test_restorable_collection_tasks_filters(tmp_path: Path):
    service = make_service(tmp_path)
    service.create("ok-1", "collection.网页采集", collection_payload("网页采集"))
    service.update("ok-1", status="failed", finished=True)
    service.create("bad-op", "collection.网页采集", collection_payload("语音采集"))
    service.update("bad-op", status="failed", finished=True)
    service.create("bad-ver", "collection.文本采集", collection_payload("文本采集", version=2))
    service.update("bad-ver", status="failed", finished=True)
    service.create("other", "generic", {"path": "a.txt"})
    service.update("other", status="failed", finished=True)
    service.create("maxed", "collection.文件采集", collection_payload("文件采集"))
    service.update("maxed", status="failed", finished=True)
    for _ in range(3):
        service.retry_task("maxed")
        service.update("maxed", status="failed", finished=True)
    rows = service.list_restorable_collection_tasks()
    assert [row["id"] for row in rows] == ["ok-1"]


def test_restorable_drops_after_retry(tmp_path: Path):
    service = make_service(tmp_path)
    service.create("ok-1", "collection.网页采集", collection_payload())
    service.update("ok-1", status="failed", finished=True)
    assert len(service.list_restorable_collection_tasks()) == 1
    service.retry_task("ok-1")
    assert service.list_restorable_collection_tasks() == []
