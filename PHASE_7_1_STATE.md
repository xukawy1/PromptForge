# Phase 7.1 状态说明

本阶段完成组件与模板 CRUD 接入主界面：
- Prompt组件页新增：新增组件（标准名/中英文名/分类/说明/使用场景）、新增写法 Variant、删除组件（级联删除写法，需确认）；
- Prompt模板页新增：新增/编辑/删除模板，变量表维护（变量名/显示名/默认值/必填），编辑时同步重建变量；系统预置模板禁止编辑与删除；
- 主窗口向模板页注入 PatternService；
- 仓库层补齐 list_all、KnowledgeRepository.search（关键词+分类过滤，返回列表）、PromptRepository.search（分页返回 items/total）与 search_text（返回列表）签名分化；
- 新增 ComponentRelationRepository（此前只存在于被遮蔽的遗留模块中，KnowledgeService 构造即崩）；
- 知识库 UI 新增条目默认 source_type=manual，避免 NOT NULL 失败；
- 新增 Phase 7 专项测试（list_all、知识/Prompt 检索结构、组件关系 CRUD、知识默认来源）。
