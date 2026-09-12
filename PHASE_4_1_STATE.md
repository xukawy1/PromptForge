# Phase 4.1 状态说明

本阶段完成图片反推本地 Metadata 解析链：
- 新增 ImageAnalysisService：解析生成图内嵌 Metadata，还原正向/负向 Prompt 与生成参数；
- 支持 Stable Diffusion WebUI 的 parameters 文本块（Steps/Sampler/CFG/Seed/Size/Model 等）；
- 支持 ComfyUI 导出的 prompt 工作流 JSON（KSampler/CLIPTextEncode/CheckpointLoaderSimple）；
- 只按文件格式标准解析，不绑定具体网站，不做动态代码执行；
- 未识别 Metadata 的图片返回 tool=none，不阻断流程；
- 图片反推页面重做：已采集图片列表、本地图片预览解析、重新解析并入库、保存为 Prompt；
- 解析结果写回 images.metadata 与 analysis_status=analyzed；
- 保存为 Prompt 时按内容哈希去重，并保留 image_id/source_id 来源追溯；
- OCR / Vision 链路预留 images.ocr_text / images.vision_result，待模型中心接入后启用；
- 主窗口向图片反推页注入 ImageAnalysisService；
- 新增 Phase 4 专项测试（A1111、ComfyUI、无元数据、入库与去重）。
