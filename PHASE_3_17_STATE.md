# Phase 3.17 状态说明

本阶段完成跨重启采集任务安全恢复执行基础：
- 新增 TaskManager.recover_persisted_collection_task；
- 仅允许文本、文件、网页三类固定采集操作；
- 校验任务类型、执行计划 kind 和 version；
- 从持久化参数恢复原始采集调用；
- 不使用 eval、exec 或动态导入函数；
- 恢复前仍检查任务状态和重试次数。
