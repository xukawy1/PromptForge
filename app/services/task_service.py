import json
from datetime import datetime, timezone
from app.database.repositories.core import TaskRepository

class TaskService:
    INTERRUPTED_MESSAGE = "程序上次退出时任务未完成，已恢复为可重试状态"
    RECOVERABLE_OPERATIONS = ("文本采集", "文件采集", "网页采集")

    def __init__(self, db_path):
        self.repo = TaskRepository(db_path)

    def create(self, task_id, task_type, input_data=None):
        return self.repo.create({"id": task_id, "task_type": task_type, "status": "pending", "progress": 0,
                                 "input_data": json.dumps(input_data or {}, ensure_ascii=False)})

    def update(self, task_id, status=None, progress=None, result_data=None, error_message=None, started=False, finished=False):
        data = {}
        if status is not None: data["status"] = status
        if progress is not None: data["progress"] = progress
        if result_data is not None: data["result_data"] = json.dumps(result_data, ensure_ascii=False, default=str)
        if error_message is not None: data["error_message"] = str(error_message)
        if started: data["started_at"] = datetime.now(timezone.utc).isoformat()
        if finished: data["finished_at"] = datetime.now(timezone.utc).isoformat()
        return self.repo.update(task_id, data)

    def get_task(self, task_id):
        return self.repo.get(task_id)

    def list_tasks(self, status=None, limit=200):
        if status and status != "全部":
            return self.repo.list(limit=limit, where="status=?", params=(status,), order_by="created_at DESC")
        return self.repo.list(limit=limit, order_by="created_at DESC")

    def can_retry(self, task_id, max_retries=3):
        row = self.get_task(task_id)
        if not row:
            return False, "任务不存在"
        if row.get("status") not in ("failed", "cancelled"):
            return False, "只有失败或已取消的任务可以重试"
        count = int(row.get("retry_count") or 0)
        if count >= max_retries:
            return False, f"任务已达到最大重试次数（{max_retries}）"
        return True, ""

    def retry_task(self, task_id, max_retries=3):
        allowed, message = self.can_retry(task_id, max_retries)
        if not allowed:
            raise ValueError(message)
        row = self.get_task(task_id)
        count = int(row.get("retry_count") or 0)
        self.repo.update(task_id, {
            "status": "pending", "progress": 0, "error_message": "",
            "result_data": "", "started_at": None, "finished_at": None,
            "retry_count": count + 1,
        })
        return self.get_task(task_id)

    def retry(self, task_id, max_retries=3):
        row = self.repo.get(task_id)
        if not row:
            raise ValueError("任务不存在")
        count = int(row.get("retry_count") or 0)
        if count >= max_retries:
            raise ValueError(f"任务已达到最大重试次数（{max_retries}）")
        return self.repo.update(task_id, {
            "status": "pending", "progress": 0, "error_message": "",
            "result_data": "", "started_at": None, "finished_at": None,
            "retry_count": count + 1,
        })


    # ---------- 历史记录删除 ----------

    ACTIVE_STATUSES = ("running", "pending")

    def delete_task(self, task_id):
        """删除一条历史记录；进行中的任务不允许删除（避免执行状态异常）。"""
        row = self.get_task(task_id)
        if not row:
            raise ValueError("任务不存在")
        if row.get("status") in self.ACTIVE_STATUSES:
            raise ValueError("该任务正在执行/排队中，请先等它完成或取消后再删除记录")
        return self.repo.delete(task_id)

    def clear_history(self):
        """清空历史记录：删除全部已结束任务；进行中/排队中的任务保留并回报数量。"""
        rows = self.repo.list(1000)
        deleted, skipped = 0, 0
        for row in rows:
            if row.get("status") in self.ACTIVE_STATUSES:
                skipped += 1
                continue
            self.repo.delete(row["id"])
            deleted += 1
        return {"deleted": deleted, "skipped": skipped}

    def retryable_tasks(self, limit=200):
        """返回当前允许重试的失败或取消任务。"""
        rows = self.list_tasks(limit=limit)
        return [row for row in rows if row.get("status") in ("failed", "cancelled")
                and int(row.get("retry_count") or 0) < 3]

    def recover_interrupted_tasks(self):
        """将程序异常退出后遗留的 running 任务恢复为可重试的 failed 状态。"""
        rows = self.repo.list(limit=500, where="status=?", params=("running",),
                             order_by="created_at DESC")
        recovered = []
        for row in rows:
            task_id = row.get("id")
            self.repo.update(task_id, {
                "status": "failed",
                "error_message": self.INTERRUPTED_MESSAGE,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            recovered.append(task_id)
        return recovered

    def list_interrupted_tasks(self, limit=200):
        """返回上次异常退出后被标记为可重试的中断任务。"""
        return self.repo.list(limit=limit, where="status=? AND error_message=?",
                              params=("failed", self.INTERRUPTED_MESSAGE),
                              order_by="created_at DESC")

    def list_restorable_collection_tasks(self, limit=200):
        """返回可跨重启恢复执行的采集任务，与恢复执行接口使用相同校验规则。"""
        restorable = []
        for row in self.list_recoverable_collection_tasks(limit=limit):
            if row.get("status") not in ("failed", "cancelled"):
                continue
            allowed, _ = self.can_retry(row.get("id"))
            if not allowed:
                continue
            plan = (row.get("input_payload") or {}).get("execution_plan") or {}
            if plan.get("version") != 1 or plan.get("operation") not in self.RECOVERABLE_OPERATIONS:
                continue
            restorable.append(row)
        return restorable

    def list_recoverable_collection_tasks(self, limit=200):
        """返回带有持久化执行计划的采集任务，供启动恢复流程使用。"""
        rows = self.list_tasks(limit=limit)
        result = []
        for row in rows:
            if not str(row.get("task_type") or "").startswith("collection."):
                continue
            try:
                payload = json.loads(row.get("input_data") or "{}")
            except (TypeError, ValueError):
                continue
            plan = payload.get("execution_plan")
            if isinstance(plan, dict) and plan.get("kind") == "collector":
                row = dict(row)
                row["input_payload"] = payload
                result.append(row)
        return result
