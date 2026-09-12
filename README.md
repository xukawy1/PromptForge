<div align="center">

# 🔥 PromptForge · AI 提示词知识工坊

**本地优先的提示词采集 · 管理 · 规整 · 生成一站式桌面工具**

`PySide6` · `SQLite` · `Ollama` · `Windows`

[功能总览](#-功能总览) · [快速开始](#-快速开始) · [接入本地大模型](#-接入本地大模型-ollama) · [架构](#-架构) · [路线图](#-路线图) · [反馈问题](../../issues)

</div>

---

## 📖 这是什么

**PromptForge** 是一款运行在你自己电脑上的 AI 提示词（Prompt）知识管理工具。它把分散在各处的提示词资料——网页文章、本地文档、生成图的内置参数、你收藏的 Skill 写作规范——统一采集入库，自动规整成**可直接用于 AI 绘画 / 视频生成的提示词**，并通过本地大模型（Ollama）实现提示词的智能扩写、按 Skill 规范改写与多语言翻译。

> 🔒 **本地优先**：所有数据（知识库、Prompt 库、模型配置）都保存在你自己的电脑上，不依赖任何云服务；AI 能力通过本地 Ollama 提供，断网也能管理知识库。

## ✨ 功能总览

| 模块 | 能力 |
|---|---|
| 🏠 **工作台** | 数据总览统计（切换自动刷新）+ 跨重启任务恢复面板 |
| 📥 **采集中心** | 手工文本 / 本地文件（TXT·MD·DOCX·PDF·图片）/ 网页 URL 三类采集；图片文字 OCR 识别；一键归纳为图片/视频提示词（可编辑、重新识别、选分类保存知识库）；采集历史回看 |
| 📚 **知识库** | 分类树管理、关键词自动分类、内置提示词包（15 张知识卡）、划词翻译（18 种语言） |
| 🧩 **Prompt 组件** | 提示词要素库（内置 8 个常用组件），每个组件支持多种写法 Variant |
| 📐 **Prompt 模板** | 变量占位符模板（内置 5 套：人像/风景/产品/H3 视频分镜/LOGO），填空即用 |
| 📖 **Prompt 库** | 全部已保存 Prompt 的分页检索、中英对照详情、来源追溯、一键同步知识库 |
| 🧠 **Skill 工坊** | 一键安装 GitHub/各大社区的 skill 文件或文件夹（内置 21 个：MiniMax H3 官方三件套、MJ 提示词工程等），按关键字调用，把知识库素材**详细扩写为符合 skill 规范的成品提示词**，支持一键翻译 |
| ✍ **Prompt 生成** | 需求 → 关键词 RAG 上下文 → 模板变量 → 本地大模型流式生成（实时进度），中英双语结果，一键入库 |
| 🖼 **图片反推** | 三种方式还原图像提示词：内嵌 Metadata 解析（A1111 / ComfyUI 工作流）、图片拖拽导入、**AI 视觉反推**（本地多模态模型看图写提示词） |
| 🤖 **模型中心** | 连接本地 Ollama，动态发现已安装模型，设置默认 LLM / Vision / Embedding（不写死任何模型名） |
| 📜 **历史记录** | 全部后台任务生命周期、失败重试、跨重启断点恢复 |
| ⚙ **设置** | 亮/暗主题、12 种强调色 + 自定义取色、**整页背景图片**（遮罩浓度可调、自动重启生效） |

## 🚀 快速开始

### 方式一：下载 exe（推荐）

从 [Releases](../../releases) 下载 `PromptForge_vX.X.X_exe_win64.zip`，解压后双击 `PromptForge.exe` 即可，无需安装 Python。

> 首次运行如遇 Windows Defender 提示（PyInstaller 打包常见误报），点「更多信息 → 仍要运行」。

### 方式二：源码运行

```bash
git clone https://github.com/xukawy1/PromptForge.git
cd PromptForge
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## 🤖 接入本地大模型（Ollama）

不装 Ollama 也能使用采集、知识库、组件/模板、图片反推（元数据解析）等全部本地功能。需要 AI 生成/翻译/视觉反推时：

```bash
# 1. 安装 Ollama（https://ollama.com）后拉取模型
ollama pull qwen3:8b        # 文本生成
ollama pull qwen2.5vl:7b    # 视觉反推（可选）
```

2. 打开软件 → **🤖 模型中心** → 确认地址 `http://127.0.0.1:11434` → 「测试连接并刷新模型」
3. 选中模型 → 设为默认 LLM / Vision → 回到对应页面即可使用

## 🧠 内置内容包

启动时自动导入（幂等，重复启动不会重复）：

- **21 个 Skill**：MiniMax H3 官方三件套（h3-prompt-writing / h3-seg-prompt-design / start-h3-prompts-from-scratch）、Midjourney 提示词工程、prompt-engine / build / enhance / library / adapt、图生提示词、GPT Image、AI 视觉故事库、8 个视频/广告创作类 skill，以及 GitHub 的 awesome-chatgpt-prompts（MIT）
- **15 张提示词知识卡**：MJ 结构与参数、SD/SDXL 结构与权重、负向提示词集合、H3 视频模板、光线/镜头/色彩词汇库、人像/风景/产品/LOGO/分镜模板、避坑清单
- **12 条成品 Prompt**：中英对照、可直接复制使用
- **8 个组件 + 5 套模板**：开箱即用的提示词要素与变量模板

## 🏗 架构

```
UI (PySide6)  →  Service  →  Repository  →  SQLite
                     ↓
              TaskManager（后台任务 / 进度 / 跨重启恢复）
                     ↓
              Provider 层（OllamaProvider：动态发现模型，不写死）
```

- **分层铁律**：UI 不直接访问数据库；模型清单一律来自服务发现
- **数据库变更**必须通过 Migration（当前版本 2）
- **安全规整**：不使用 eval/exec，不执行数据库中的字符串代码
- 60 个 pytest 测试覆盖核心链路

## 🗺 路线图

- [x] v0.6 采集识别归纳闭环 / Skill 工坊 / 整页背景 / 划词翻译
- [ ] 向量 RAG（Embedding 相似度检索替代关键词检索）
- [ ] Vision 反推深度集成（批量图片、视频抽帧）
- [ ] Prompt DNA / Pattern 发现 / 提示词评分
- [ ] 更多 Provider（OpenAI 兼容接口、ComfyUI 集成）

## 🙋 反馈问题

使用中遇到任何问题（报错、功能异常、界面建议），欢迎到 [Issues](../../issues) 反馈：

- 🐛 **[报告问题](../../issues/new?template=bug_report.yml)** — 选择模块、描述现象，可附日志与截图
- 💡 **[功能建议](../../issues/new?template=feature_request.yml)** — 说出你想要的功能

会在看到后尽快回复。

## 🤝 贡献

欢迎 Issue 与 PR！提交前请运行 `python -m pytest tests -q` 确保测试通过。

## 📄 许可证

[MIT License](LICENSE)
