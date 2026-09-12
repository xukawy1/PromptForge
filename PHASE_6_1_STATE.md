# Phase 6.1 状态说明

本阶段完成 Prompt 生成接入：
- 新增 GenerationService：需求 → 关键词上下文检索（知识/文档/Prompt）→ 模板填充 → Ollama 生成 → 历史入库；
- 系统提示词固定输出"正向 Prompt / Negative prompt / 参数"结构，生成结果可自动拆解；
- 上下文检索为关键词 RAG，检索结果连同生成请求写入 generation_history.retrieved_context；
- 支持模板生成：按 prompt_templates 变量填充占位符，补充需求合并进请求；
- 生成历史记录最近列表，结果可一键保存到 Prompt 库（按内容哈希去重，记录 target_model）；
- Prompt生成页面重做：需求输入、模板与变量动态表单、上下文开关、后台生成（TaskManager 进度/失败回调）、结果解析、保存入库、最近生成记录；
- 修复启动阻断问题：repositories 包补齐 ComponentRelationRepository（KnowledgeService 构造即崩）；
- 修复知识库关键词搜索：KnowledgeRepository.search 按关键词+分类过滤并返回列表；
- 修复 PromptRepository.search/search_text 签名冲突（分页检索返回 items/total，关键词检索返回列表）；
- 修复 UI 新增知识缺 source_type 导致 NOT NULL 失败的问题；
- 新增 Phase 6 专项测试（结果解析、模板填充、上下文检索、无默认模型报错、生成入库与去重、模板生成请求）。
