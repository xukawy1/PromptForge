# PromptForge Phase 3.2 状态

## 已完成
- 文本采集自动识别标题：Markdown 一级/多级标题、首个有效行、文件名/正文前缀回退。
- 轻量语言识别：zh / en / zh-en / other / unknown。
- 内容类型识别：text / markdown / prompt / json。
- 字符数、计数单位、行数统计。
- 文档 summary 初步生成，为后续 AI 摘要替换预留。
- TXT/MD/CSV/JSON/LOG 显示实际解码编码。
- DOCX 记录表格数量。
- PDF 记录页数。
- 图片结果展示尺寸、格式、Hash。
- 采集失败统一返回 failed 结果，UI展示异常。
- 采集中心增加实时文本统计和本次采集结果详情。
- 保持 Source / Document / Image 入库模型不变，无破坏性数据库迁移。

## 未进入本阶段
- URL/微信公众号网页采集：3.4。
- OCR/Vision：后续图片分析阶段。
- 完整采集历史：3.8。
- 后台任务进度：3.7。

## 验收
- pytest
- compileall
- 本地 SQLite 文本、重复文本测试
