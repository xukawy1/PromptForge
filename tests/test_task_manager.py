import time
from PySide6.QtCore import QCoreApplication
from app.tasks.task_manager import TaskManager

def test_task_manager():
    app = QCoreApplication.instance() or QCoreApplication([])
    manager = TaskManager(max_workers=1)
    seen = []
    manager.task_finished.connect(lambda task_id, result: seen.append((task_id, result)))
    task_id, future, ctx = manager.submit(fn=lambda c: "ok")
    assert future.result(timeout=3) == "ok"
    deadline = time.time() + 3
    while not seen and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert seen and seen[0][0] == task_id
    manager.shutdown()
