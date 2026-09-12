# PromptForge AI续接说明

当前项目：PromptForge（提示词工坊）

当前版本：v0.2.0

当前阶段：V1.0 核心功能已齐（Phase 3 任务恢复链 + Phase 4 图片反推 + Phase 5 模型中心/Provider + Phase 6 Prompt生成 + Phase 7 组件/模板 CRUD）。

## 已经完成
- PySide6 骨架、主题系统、设置持久化
- SQLite 全量业务表、Migration、Repository / Service / TaskManager 分层
- 采集中心（文本/文件/网页 + 后台任务 + 跨重启恢复链 3.15~3.19）
- 图片反推（A1111 / ComfyUI Metadata 解析、入库、存为 Prompt）
- Provider 层（OllamaProvider：动态发现/生成/向量化）与模型中心
- Prompt 生成（关键词 RAG、模板变量、历史、入库去重）
- 知识库 / 组件 / 模板 / Pattern 完整 CRUD
- 测试 44 个（pytest），全部通过；离屏冒烟 10 页面全切换通过

## 重要UI要求
设置页面必须保留：跟随系统 / 浅色 / 深色 / 强调色预设 / 自定义颜色，均持久化到 config.json。

## 开发规则
不要推倒重写。
不要删除已有功能。
不要绕过 Service / Provider / Repository 分层。
不要把模型写死（模型清单一律来自 Ollama 服务发现）。
不要把网页解析写死（按文件格式/网页标准解析）。
修改数据库必须通过 Migration（当前 schema_migrations 版本 1）。
每完成一个阶段，更新 PROJECT_STATE.md 和 CHANGELOG.md。
每个阶段打包：python -m compileall → pytest → zip → 解压复测 → 复制到 Downloads。

## 下一步候选（V1.5 方向）
- Vision 链路：模型中心设置默认 Vision 后，图片反推走 Ollama Vision 模型
- 向量 RAG：Embedding 模型 + embeddings 表做相似度检索，替代关键词 RAG
- Prompt DNA / Pattern 发现 / Prompt 评分
- ComfyUI Metadata 深度解析、更多 Provider（OpenAI 兼容接口等）
