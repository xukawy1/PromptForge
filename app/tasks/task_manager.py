from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4
from PySide6.QtCore import QObject, Signal
from app.tasks.execution_registry import TaskExecutionRegistry

class TaskContext:
    def __init__(self, task_id):
        self.task_id = task_id
        self._progress = 0.0
        self._cancelled = False
        self._lock = Lock()
    @property
    def progress(self):
        with self._lock: return self._progress
    @property
    def cancelled(self):
        with self._lock: return self._cancelled
    def set_progress(self, value):
        with self._lock: self._progress = max(0.0, min(100.0, float(value)))
    def cancel(self):
        with self._lock: self._cancelled = True

class TaskManager(QObject):
    task_started = Signal(str)
    task_progress = Signal(str, float)
    task_finished = Signal(str, object)
    task_failed = Signal(str, str)
    task_cancelled = Signal(str)
    task_state = Signal(str, str, float)

    def __init__(self, task_service=None, max_workers=4):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.task_service = task_service
        self._contexts, self._futures = {}, {}
        self.execution_registry = TaskExecutionRegistry()
        self._lock = Lock()

    def submit(self, task_id=None, fn=None, *args, task_type="generic", input_data=None, allow_existing=False, **kwargs):
        if fn is None: raise ValueError("fn 不能为空")
        task_id = task_id or str(uuid4())
        if self.task_service and self.task_service.get_task(task_id) and not allow_existing:
            raise ValueError(f"任务ID已存在：{task_id}")
        context = TaskContext(task_id)
        self.execution_registry.register(task_id, task_type, fn, args, kwargs)
        if self.task_service:
            if allow_existing:
                self.task_service.update(task_id, status="pending", progress=0,
                                         error_message="", result_data=None)
            else:
                self.task_service.create(task_id, task_type, input_data)
        with self._lock: self._contexts[task_id] = context
        self.task_started.emit(task_id)
        self.task_state.emit(task_id, "running", 0.0)
        if self.task_service: self.task_service.update(task_id, "running", 0, started=True)
        def progress(value):
            context.set_progress(value); self.task_progress.emit(task_id, context.progress); self.task_state.emit(task_id, "running", context.progress)
            if self.task_service: self.task_service.update(task_id, progress=context.progress)
        context.report_progress = progress
        def runner():
            try:
                result = fn(context, *args, **kwargs)
                if context.cancelled:
                    if self.task_service: self.task_service.update(task_id, "cancelled", context.progress, finished=True)
                    self.task_cancelled.emit(task_id); self.task_state.emit(task_id, "cancelled", context.progress)
                else:
                    progress(100)
                    if self.task_service: self.task_service.update(task_id, "completed", 100, result_data=result, finished=True)
                    self.task_finished.emit(task_id, result); self.task_state.emit(task_id, "completed", 100.0)
                return result
            except Exception as exc:
                if context.cancelled:
                    if self.task_service: self.task_service.update(task_id, "cancelled", context.progress, error_message=str(exc), finished=True)
                    self.task_cancelled.emit(task_id)
                else:
                    if self.task_service: self.task_service.update(task_id, "failed", context.progress, error_message=str(exc), finished=True)
                    self.task_failed.emit(task_id, str(exc)); self.task_state.emit(task_id, "failed", context.progress)
                raise
            finally:
                with self._lock:
                    self._contexts.pop(task_id, None); self._futures.pop(task_id, None)
                    self.execution_registry.remove(task_id)
        future = self.executor.submit(runner)
        with self._lock: self._futures[task_id] = future
        return task_id, future, context

    def retry_registered(self, task_id):
        """重新提交本进程内仍登记着执行器的失败/取消任务。"""
        if not self.task_service:
            raise RuntimeError("未配置任务服务")
        allowed, message = self.task_service.can_retry(task_id)
        if not allowed:
            raise ValueError(message)
        item = self.execution_registry.get(task_id)
        if not item:
            raise ValueError("原任务执行器已失效，请从采集中心重新提交")
        self.task_service.retry_task(task_id)
        return self.submit(task_id=task_id, fn=item["fn"], *item["args"],
                           task_type=item["task_type"], allow_existing=True, **item["kwargs"])

    def recover_persisted_collection_task(self, task_id, collector_service):
        """按固定白名单恢复持久化采集任务，禁止动态执行任意函数。"""
        if not self.task_service:
            raise RuntimeError("未配置任务服务")
        row = self.task_service.get_task(task_id)
        if not row:
            raise ValueError("任务不存在")
        task_type = str(row.get("task_type") or "")
        if not task_type.startswith("collection."):
            raise ValueError("该任务不是采集任务")
        try:
            payload = __import__("json").loads(row.get("input_data") or "{}")
        except (TypeError, ValueError) as exc:
            raise ValueError("任务执行参数损坏") from exc
        plan = payload.get("execution_plan") or {}
        if plan.get("kind") != "collector" or plan.get("version") != 1:
            raise ValueError("不支持的任务执行计划版本")
        operation = plan.get("operation")
        raw_args = payload.get("args", [])
        if not isinstance(raw_args, list) or len(raw_args) > 8:
            raise ValueError("任务参数格式无效")
        if any(not isinstance(value, (str, int, float, bool, type(None))) for value in raw_args):
            raise ValueError("任务参数包含不支持的数据类型")
        mapping = {
            "文本采集": collector_service.collect_text,
            "文件采集": collector_service.collect_file,
            "网页采集": collector_service.collect_url,
        }
        fn = mapping.get(operation)
        item = (fn, raw_args) if fn else None
        if not item:
            raise ValueError(f"不支持恢复的采集操作：{operation}")
        allowed, message = self.task_service.can_retry(task_id)
        if not allowed:
            raise ValueError(message)
        self.task_service.retry_task(task_id)
        fn, args = item
        def worker(ctx, *worker_args):
            ctx.report_progress(5)
            result = fn(*worker_args)
            ctx.report_progress(95)
            return result
        return self.submit(task_id=task_id, fn=worker, *args,
                           task_type=task_type, input_data=payload,
                           allow_existing=True)

    def running_count(self):
        with self._lock:
            return len(self._contexts)

    def cancel(self, task_id):
        with self._lock:
            context, future = self._contexts.get(task_id), self._futures.get(task_id)
        if context: context.cancel()
        return bool(future and future.cancel()) or bool(context)

    def shutdown(self): self.executor.shutdown(wait=True, cancel_futures=True)
