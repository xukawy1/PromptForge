# Phase 3.11 状态说明

- 清理 TaskManager 取消信号重复发射问题。
- 增加 TaskService.retryable_tasks()。
- 保持历史页重试行为与数据库结构兼容。
- 为后续统一任务执行器和真正自动重试预留接口。
