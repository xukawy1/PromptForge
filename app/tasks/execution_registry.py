from threading import RLock


class TaskExecutionRegistry:
    """安全的任务执行注册表，只允许业务代码显式注册执行器。"""
    def __init__(self):
        self._items = {}
        self._lock = RLock()

    def register(self, task_id, task_type, fn, args=(), kwargs=None):
        if not task_id or not task_type or not callable(fn):
            raise ValueError("任务执行器注册参数无效")
        with self._lock:
            self._items[task_id] = {
                "task_type": task_type, "fn": fn,
                "args": tuple(args), "kwargs": dict(kwargs or {})
            }

    def get(self, task_id):
        with self._lock:
            item = self._items.get(task_id)
            return dict(item) if item else None

    def remove(self, task_id):
        with self._lock:
            self._items.pop(task_id, None)

    def clear(self):
        with self._lock:
            self._items.clear()
