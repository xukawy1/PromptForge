# Phase 3.19 状态说明

本阶段完成启动恢复任务提示面板，让跨重启任务恢复在工作台直观可见：
- 工作台新增"任务恢复"面板：显示上次中断任务数量与可恢复采集任务数量；
- 面板列出可恢复采集任务（任务ID、采集操作、状态、重试次数）；
- 支持"恢复选中任务"（逐项恢复）与"全部恢复"，通过固定白名单映射恢复执行；
- 支持"忽略"隐藏本次提示；忽略只对当前运行生效，重启后如仍有未处理任务会再次提示；
- 未连接任务执行器时恢复按钮禁用，并提示可在历史记录页手动重试；
- TaskService 新增 INTERRUPTED_MESSAGE 与 RECOVERABLE_OPERATIONS 常量，
  recover_interrupted_tasks 改用统一常量标记中断任务；
- TaskService 新增 list_interrupted_tasks 与 list_restorable_collection_tasks，
  后者与恢复执行接口使用相同校验规则（状态、重试次数、计划版本、操作白名单）；
- 主窗口向工作台注入 TaskService / TaskManager / CollectorService；
- 新增 Phase 3.19 专项测试（tests/test_phase3_19_recovery_panel.py）；
- test_services.py 改用 tmp_path，修复 Windows 下临时目录清理被 SQLite 文件占用阻塞的问题；
- 历史记录页原有重试入口保持不变，两个入口共用同一套恢复校验。
