# Phase 3.16 状态说明

本阶段完成持久化任务执行计划基础：
- 采集任务类型细分为 collection.文本采集、collection.文件采集、collection.网页采集；
- 将采集原始参数保存到 tasks.input_data；
- 写入版本化 execution_plan，便于后续跨重启恢复；
- TaskService 增加带执行计划的采集任务查询接口；
- 当前阶段只保存和校验执行计划，不会直接执行数据库中的函数或参数。
