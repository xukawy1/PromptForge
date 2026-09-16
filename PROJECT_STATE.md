# PromptForge 项目状态

版本：v0.8.7

## 已完成
- Phase 0：产品设计、UI/UX、数据库、AI协议、技术架构
- Phase 1：PySide6骨架、主题系统、SQLite全量表、Repository/Service/TaskManager
- Phase 2：知识库核心（分类/来源/文档/Prompt/组件/标签/结构化）
- Phase 3：采集中心全链路（文本/文件/网页、后台任务、断点跨重启恢复 3.15~3.19）
- Phase 4：图片反推（A1111 / ComfyUI Metadata 解析入库）
- Phase 5：Provider层（Ollama）+ 模型中心（动态发现、默认模型）
- Phase 6：Prompt生成（关键词RAG、模板变量、Ollama、历史与入库）
- Phase 7：组件/模板完整CRUD、仓库层统一、v0.2.0 发布
- Phase 8：用户反馈优化——图标、QSS主题、背景图、工作台刷新、采集预览/历史、Prompt库页面、双语流式生成、图片拖拽+AI视觉反推
- Phase 9：二轮反馈——采集中心分区导航、智能规整同步知识库、Prompt库↔知识库同步、Skill 工坊（skills 表）、背景图整页铺满

## 当前架构
UI → Service → Repository → SQLite
耗时操作：UI → TaskManager → Service/Provider
外部AI能力：OllamaProvider（动态发现模型，不写死；生成/向量化已接入，Vision 预留）

## 验收
pytest 60 个全部通过；内置 Skill 21 个（另已内置 13 个 Skill 与 15+12 条种子内容）；离屏冒烟：主窗口 12 个页面全部构造并切换正常；exe 已带应用图标。

## V1.5 候选
Vision 反推链路、向量 RAG（embeddings 表）、Prompt DNA / Pattern 发现、评分、ComfyUI 深度解析。

## 架构冻结规则
Phase 1之后原则上不改变核心分层。需要修改架构时必须记录影响范围、迁移方案和回滚方案。
