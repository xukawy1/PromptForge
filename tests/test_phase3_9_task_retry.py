from pathlib import Path
from app.database.migrations import migrate
from app.services.task_service import TaskService

def test_task_list_get_and_retry(tmp_path: Path):
    db = tmp_path / "tasks.db"
    migrate(db)
    service = TaskService(db)
    service.create("retry-1", "collector", {"path": "a.txt"})
    service.update("retry-1", status="failed", progress=40, error_message="网络超时", finished=True)
    assert service.get_task("retry-1")["status"] == "failed"
    assert len(service.list_tasks()) == 1
    assert service.can_retry("retry-1")[0] is True
    row = service.retry_task("retry-1")
    assert row["status"] == "pending"
    assert row["progress"] == 0
    assert row["retry_count"] == 1
    assert service.can_retry("retry-1")[0] is False

def test_retry_limit(tmp_path: Path):
    db = tmp_path / "tasks.db"
    migrate(db)
    service = TaskService(db)
    service.create("retry-2", "collector")
    service.update("retry-2", status="failed", finished=True)
    service.retry_task("retry-2", max_retries=1)
    service.update("retry-2", status="failed", finished=True)
    try:
        service.retry_task("retry-2", max_retries=1)
    except ValueError as exc:
        assert "最大重试次数" in str(exc)
    else:
        raise AssertionError("应阻止超过最大重试次数")
