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


def test_delete_and_clear_history(tmp_path: Path):
    from app.database.migrations import migrate
    from app.services.task_service import TaskService
    db = tmp_path / "hist.db"
    migrate(db)
    service = TaskService(db)
    service.create("done-1", "collection.文本采集", {"label": "文本采集", "args": ["x", ""],
                                                      "execution_plan": {"kind": "collector", "operation": "文本采集", "version": 1}})
    service.update("done-1", status="completed", finished=True)
    service.create("fail-1", "collection.文件采集", {"label": "文件采集", "args": ["a.txt"],
                                                     "execution_plan": {"kind": "collector", "operation": "文件采集", "version": 1}})
    service.update("fail-1", status="failed", error_message="x", finished=True)
    service.create("run-1", "collection.网页采集", {"label": "网页采集", "args": ["http://x", ""],
                                                    "execution_plan": {"kind": "collector", "operation": "网页采集", "version": 1}})
    service.update("run-1", status="running", started=True)

    # 单条删除：已结束可删
    assert service.delete_task("done-1") is True
    assert service.get_task("done-1") is None
    # 进行中不可删
    import pytest
    with pytest.raises(ValueError):
        service.delete_task("run-1")

    # 清空：删除已结束，保留进行中
    outcome = service.clear_history()
    assert outcome == {"deleted": 1, "skipped": 1}
    assert service.get_task("fail-1") is None
    assert service.get_task("run-1") is not None
