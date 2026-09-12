# Phase 5.1 状态说明

本阶段完成模型中心与 Provider 层，并修复 UI 无法启动的类名问题：
- 新增 Provider 抽象（app/services/providers/base.py）与 OllamaProvider 实现；
- OllamaProvider 通过 /api/tags 动态发现模型，/api/generate 生成，/api/embeddings 向量化；
- 不写死任何模型名；默认模型保存在 config 的 default_llm / default_vision / default_embedding；
- 连接失败抛出可读的中文错误，不中断程序；
- 新增 ModelService：连接测试、模型动态发现与归类（llm/vision/embedding 关键词识别）、
  同步到 models 表（含参数量、量化信息）、默认模型读写；
- 模型中心页面重做：服务地址配置、测试连接并刷新模型、模型表格、设为默认 LLM/Vision/Embedding；
- 模型中心的网络请求通过 TaskManager 后台执行，带进度与失败回调；
- 修复组件/模板/生成/模型四个页面类名与主窗口导入不一致导致 UI 无法启动的问题
  （Prompt组件Page→ComponentsPage 等），此前打包版本主界面会直接 ImportError；
- 新增 Phase 5 专项测试（模型发现、分类、生成/向量请求负载、连接错误、同步与默认模型）。
