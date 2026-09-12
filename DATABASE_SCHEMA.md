# PromptForge 数据库设计

当前数据库版本：1

Phase 1.1 仅建立数据库初始化与 Migration 框架。

正式业务表将在 Phase 1.2 逐步通过 migration 创建：
- sources
- documents
- images
- prompts
- categories
- tags
- prompt_tags
- prompt_components
- prompt_component_variants
- prompt_component_relations
- prompt_patterns
- prompt_templates
- template_components
- knowledge_items
- embeddings
- models
- generation_history
- tasks
- settings

禁止直接修改已执行的 migration；需要变更时新增 migration。
