# Phase 14.1 状态说明（v0.7.0）

1. 网页多风格识别：采集中心网页页新增「识别多种风格…」——调用默认 LLM 分析来源内容
   （正文+图片 OCR），识别其中体现的多种提示词风格（最多 6 种，如写实摄影/电影感/赛博朋克/国风水墨等），
   每种风格生成一段可直接复制的完整提示词；弹出独立窗体以卡片形式展示（可编辑、可勾选），
   用户选择后统一选知识分类保存为多条知识条目（标题 = 来源标题 · 风格名，source_type=multi_style）；
   JSON 解析带兜底（模型未按格式输出时作为单一"综合风格"展示）；
2. 默认模型持久记忆：模型中心表格新增"点击任意一行即自动记住为默认 LLM"，无需再手动点按钮；
   set_default 在写入 config 的同时标记 models.is_default；启动时若 config 缺失自动从 models 表恢复，
   同目录使用下重启软件永久保持上次选择的模型；
3. 新增 API 调用接口（OpenAI 兼容协议）：新增 OpenAICompatProvider（/chat/completions 生成、SSE 流式、
   多模态 vision、/models 动态发现），内置厂商预设：OpenAI / DeepSeek / 智谱 GLM / 月之暗面 Kimi /
   通义千问 / 自定义 Base URL；模型中心新增「API 接入」分组（厂商下拉自动填地址、密钥掩码输入、
   保存并测试连接、模型清单并入总表，provider 标记 api:<vendor>）；
   新增 ModelService.provider_for(model) 按模型来源自动路由（ollama 或 API），
   生成/翻译/Skill 扩写/视觉反推/规整 全部调用点已切换路由；
4. 其余功能零改动；新增 Phase 14 专项测试（OpenAI 兼容生成/流式/视觉/错误文案、provider 路由、
   默认模型持久化恢复、多风格识别解析与兜底），65 个测试全绿。
