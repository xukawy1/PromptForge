import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QSplitter, QProgressBar,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


class ImageAnalysisPage(QWidget):
    def __init__(self, image_service=None, knowledge_service=None, model_service=None, task_manager=None):
        super().__init__()
        self.image_service = image_service
        self.knowledge_service = knowledge_service
        self.model_service = model_service
        self.task_manager = task_manager
        self.items = []
        self.current = None
        self._active_tasks = {}
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        title = QLabel("图片反推")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "三种反推方式：① 生成图内嵌 Metadata 自动解析（A1111 / ComfyUI）；"
            "② 把图片直接拖进本页；③ 用本地多模态模型 AI 看图反推（需在模型中心设置 Vision/LLM 模型）。"
        ))

        splitter = QSplitter()
        left = QWidget(); left_layout = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setIconSize(QPixmap(96, 96).size())
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setSpacing(4)
        self.list.currentRowChanged.connect(self.show)
        left_layout.addWidget(self.list)
        btns = QHBoxLayout()
        refresh_btn = QPushButton("刷新已采集图片")
        refresh_btn.clicked.connect(self.refresh)
        local_btn = QPushButton("选择本地图片…")
        local_btn.clicked.connect(self.pick_local)
        btns.addWidget(refresh_btn)
        btns.addWidget(local_btn)
        btns.addStretch()
        left_layout.addLayout(btns)
        self.preview = QLabel("图片预览（可将图片直接拖入本页；点击左侧缩略图切换）")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(260)
        self.preview.setStyleSheet("border: 1px dashed #9CA3AF; border-radius: 8px; color:#9CA3AF;")
        left_layout.addWidget(self.preview)
        splitter.addWidget(left)

        right = QWidget(); right_layout = QVBoxLayout(right)
        self.detail_title = QLabel("解析结果")
        self.detail_title.setObjectName("sectionTitle")
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail_title)
        right_layout.addWidget(self.detail, 1)

        ai_label = QLabel("AI 视觉反推（图片 → 本地多模态模型 → 提示词）")
        ai_label.setObjectName("sectionTitle")
        right_layout.addWidget(ai_label)
        self.instruction = QTextEdit()
        self.instruction.setPlaceholderText(
            "反推指令（留空使用内置默认指令）：例如“反推这段视频画面的运镜与主体，输出适合 MiniMax H3 的视频提示词”……")
        self.instruction.setMaximumHeight(64)
        right_layout.addWidget(self.instruction)
        ai_row = QHBoxLayout()
        self.vision_btn = QPushButton("开始 AI 反推")
        self.vision_btn.clicked.connect(self.run_vision)
        self.save_ai_btn = QPushButton("保存 AI 结果到 Prompt 库")
        self.save_ai_btn.clicked.connect(self.save_ai_prompt)
        self.save_btn = QPushButton("保存 Metadata 解析到 Prompt 库")
        self.save_btn.clicked.connect(self.save_prompt)
        ai_row.addWidget(self.vision_btn)
        ai_row.addWidget(self.save_ai_btn)
        ai_row.addWidget(self.save_btn)
        ai_row.addStretch()
        right_layout.addLayout(ai_row)
        self.vision_bar = QProgressBar()
        self.vision_bar.setRange(0, 0)
        self.vision_bar.setVisible(False)
        right_layout.addWidget(self.vision_bar)
        self.result = QLabel("")
        self.result.setObjectName("panelHint")
        self.result.setWordWrap(True)
        right_layout.addWidget(self.result)
        splitter.addWidget(right)
        splitter.setSizes([360, 640])
        layout.addWidget(splitter, 1)
        self.refresh()
        if self.task_manager:
            self.task_manager.task_progress.connect(self._on_task_progress)
            self.task_manager.task_finished.connect(self._on_task_finished)
            self.task_manager.task_failed.connect(self._on_task_failed)

    # ---------- 拖拽 ----------

    def dragEnterEvent(self, event: QDragEnterEvent):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(Path(u.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in IMAGE_SUFFIXES:
                self._analyze_local(path)
                event.acceptProposedAction()
                return

    # ---------- 数据 ----------

    def refresh(self):
        self.items = self.image_service.list_images() if self.image_service else []
        self.list.clear()
        for x in self.items:
            status = x.get("analysis_status") or "pending"
            mark = "已解析" if status == "analyzed" else "待解析"
            item = QListWidgetItem(f"{Path(x.get('file_path') or '').name}\n（{mark}）")
            path = x.get("file_path") or ""
            if path and Path(path).exists():
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)))
            item.setToolTip("点击后在右侧查看图片并反推")
            self.list.addItem(item)

    def pick_local(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff)")
        if path:
            self._analyze_local(path)

    def _analyze_local(self, path):
        try:
            analysis = self.image_service.analyze_path(path) if self.image_service else {}
        except Exception as exc:
            QMessageBox.warning(self, "解析失败", str(exc))
            return
        self.current = {"local_path": path, "analysis": analysis}
        self.detail_title.setText(f"本地图片：{Path(path).name}")
        self.detail.setPlainText(self._format(analysis))
        self.result.setText("Metadata 解析完成；如需 AI 看图反推，请直接点击“开始 AI 反推”。")
        self._set_preview(path)

    def _set_preview(self, path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.preview.setText("图片无法预览")
            return
        self.preview.setPixmap(
            pixmap.scaled(self.preview.width(), max(200, self.preview.height()),
                          Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def show(self, row):
        if not 0 <= row < len(self.items):
            return
        x = self.items[row]
        self.current = {"image_id": x["id"], "row": row, "file_path": x.get("file_path")}
        self.detail_title.setText(f"图片 #{x['id']}：{Path(x.get('file_path') or '').name}")
        if x.get("file_path") and Path(x["file_path"]).exists():
            self._set_preview(x["file_path"])
        try:
            metadata = json.loads(x.get("metadata") or "{}")
        except Exception:
            metadata = {}
        analysis = metadata.get("generation_metadata") if isinstance(metadata, dict) else None
        if isinstance(analysis, dict) and (analysis.get("positive") or analysis.get("negative")):
            self.detail.setPlainText(self._format(analysis))
        else:
            self.detail.setPlainText("尚未解析内嵌 Metadata。点击“保存 Metadata 解析到 Prompt 库”前请先在采集中心重新采集，"
                                     "或直接使用 AI 视觉反推。")
        self.result.setText("")

    def reparse(self, image_id=None):
        target = image_id or (self.current or {}).get("image_id")
        if not target or not self.image_service:
            return
        try:
            analysis = self.image_service.analyze_image(target)
        except Exception as exc:
            self.result.setText(f"解析失败：{exc}")
            return
        self.detail.setPlainText(self._format(analysis))
        self.result.setText("解析完成，已写入图片记录。")
        self.refresh()

    # ---------- AI 视觉反推 ----------

    def run_vision(self):
        if not (self.image_service and self.model_service):
            self.result.setText("图片服务尚未初始化。")
            return
        current = self.current or {}
        image_path = current.get("file_path") or current.get("local_path")
        if not image_path or not Path(image_path).exists():
            self.result.setText("请先选择、拖入或在列表中选中一张图片。")
            return
        instruction = self.instruction.toPlainText().strip() or None
        self.vision_btn.setEnabled(False)
        self.vision_bar.setVisible(True)
        self.result.setText("AI 反推中：图片已发送给本地多模态模型，首次加载模型可能需要较长时间……")
        if not self.task_manager:
            try:
                outcome = self.image_service.vision_analyze(image_path, self.model_service, instruction)
                self._handle_vision(outcome)
            except Exception as exc:
                self._vision_error(str(exc))
            finally:
                self.vision_btn.setEnabled(True)
                self.vision_bar.setVisible(False)
            return
        if self._active_tasks:
            self.result.setText("已有 AI 反推任务在执行。")
            self.vision_btn.setEnabled(True)
            self.vision_bar.setVisible(False)
            return

        def worker(ctx):
            ctx.report_progress(30)
            outcome = self.image_service.vision_analyze(image_path, self.model_service, instruction)
            ctx.report_progress(95)
            return outcome

        task_id, future, ctx = self.task_manager.submit(
            fn=worker, task_type="imageanalysis.vision", input_data={"image": str(image_path)}
        )
        self._active_tasks[task_id] = {"path": image_path, "image_id": current.get("image_id")}

    def _on_task_progress(self, task_id, value):
        if task_id in self._active_tasks:
            self.result.setText(f"AI 反推中……{value:.0f}%")

    def _on_task_finished(self, task_id, outcome):
        if task_id not in self._active_tasks:
            return
        info = self._active_tasks.pop(task_id)
        self.vision_btn.setEnabled(True)
        self.vision_bar.setVisible(False)
        self._handle_vision(outcome, info)

    def _on_task_failed(self, task_id, message):
        if task_id not in self._active_tasks:
            return
        self._active_tasks.pop(task_id)
        self.vision_btn.setEnabled(True)
        self.vision_bar.setVisible(False)
        self._vision_error(message)

    def _handle_vision(self, outcome, info=None):
        text = outcome.get("text") or ""
        self.detail_title.setText(f"AI 反推结果（模型：{outcome.get('model', '')}）")
        self.detail.setPlainText(text)
        self.current = self.current or {}
        self.current["ai_text"] = text
        self.current["ai_model"] = outcome.get("model", "")
        if info and info.get("image_id"):
            self.current["image_id"] = info["image_id"]
        if info and info.get("path"):
            self.current.setdefault("local_path", info["path"])
        self.result.setText("AI 反推完成，可点击“保存 AI 结果到 Prompt 库”。")

    def _vision_error(self, message):
        from app.ui.model_center_nav import is_model_missing, offer_model_center
        if is_model_missing(message):
            self.result.setText(f"需要先配置模型：{message}")
            offer_model_center(self, message)
            return
        self.result.setText(f"AI 反推失败：{message}")
        QMessageBox.warning(self, "AI 反推失败", message)

    # ---------- 保存 ----------

    def save_ai_prompt(self):
        text = (self.current or {}).get("ai_text")
        if not text or not self.image_service:
            self.result.setText("还没有 AI 反推结果。")
            return
        try:
            outcome = self.image_service.save_prompt_text(text, image_id=(self.current or {}).get("image_id"))
        except Exception as exc:
            self.result.setText(f"保存失败：{exc}")
            return
        self.result.setText(outcome.get("message", "已保存"))

    def save_prompt(self):
        current = self.current or {}
        analysis = current.get("analysis")
        if not analysis or not self.image_service:
            self.result.setText("当前没有 Metadata 解析结果可保存（那是内嵌元数据图片才有的）。")
            return
        try:
            if "image_id" in current:
                outcome = self.image_service.save_as_prompt(current["image_id"])
            else:
                outcome = self.image_service.save_prompt_text(
                    analysis.get("positive") + (f"\nNegative prompt: {analysis['negative']}" if analysis.get("negative") else ""),
                    title=f"图片反推：{Path(current.get('local_path') or '未命名').stem}",
                )
        except Exception as exc:
            self.result.setText(f"保存失败：{exc}")
            return
        self.result.setText(outcome.get("message", "已保存"))

    @staticmethod
    def _format(analysis):
        tool = analysis.get("tool") or "none"
        tool_names = {"a1111": "Stable Diffusion WebUI (parameters)", "comfyui": "ComfyUI 工作流", "none": "未识别到内嵌生成 Metadata（普通图片请用 AI 反推）"}
        lines = [f"工具：{tool_names.get(tool, tool)}"]
        if analysis.get("source_key"):
            lines.append(f"来源字段：{analysis['source_key']}")
        if analysis.get("raw_keys"):
            lines.append(f"内嵌字段：{', '.join(analysis['raw_keys'])}")
        lines.append("")
        lines.append("正向 Prompt：")
        lines.append(analysis.get("positive") or "（空）")
        lines.append("")
        lines.append("负向 Prompt：")
        lines.append(analysis.get("negative") or "（空）")
        settings = analysis.get("settings") or {}
        if settings:
            lines.append("")
            lines.append("生成参数：")
            for key, value in settings.items():
                lines.append(f"  {key}: {value}")
        if analysis.get("error"):
            lines.append("")
            lines.append(f"警告：{analysis['error']}")
        return "\n".join(lines)
