# PromptForge Phase 3.1 状态

## 已完成
- 采集中心 UI 从占位页升级为真实可用页面。
- 手工文本采集：标题、正文、本地入库。
- TXT/MD/CSV/JSON/LOG 文本文件采集，支持 UTF-8/GB18030 等编码回退。
- DOCX 文字与表格提取。
- PDF 文本提取；扫描 PDF 明确提示后续 OCR。
- PNG/JPG/JPEG/WEBP/BMP/GIF/TIFF 图片采集。
- 图片 SHA-256 去重，并复制到知识库图片目录保存。
- Source / Document / Image 实体入库。
- 重复资料识别并返回已有记录。
- 与现有 TaskManager 接口预留，后续 3.7 接入后台任务进度。

## 未进入本阶段
- URL/微信公众号网页采集：Phase 3.4。
- OCR / Vision：后续图片分析阶段。
- 完整采集历史页：3.8。

## 验收
- 运行 pytest。
- 编译全部 Python 模块。
- 使用临时 SQLite 实际测试文本、TXT、DOCX、PDF、图片及重复导入。
