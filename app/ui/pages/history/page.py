import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QSplitter, QGroupBox,
    QHeaderView, QMessageBox,
)
from app.database.repositories.core import TaskRepository
from app.services.task_service import TaskService

STATUS_LABELS = {
    "全部": "全部状态",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "running": "进行中",
    "pending": "排队中",
}


class HistoryPage(QWidget):
    def __init__(self, db_path=None, task_manager=None, collector_service=None):
        super().__init__()
        self.repo = TaskRepository(db_path) if db_path else None
        self.task_service = TaskService(db_path) if db_path else None
        self.db_path = db_path
        self.task_manager = task_manager
        self.collector_service = collector_service

        layout = QVBoxLayout(self)
        title = QLabel("历史记录")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("全部后台任务的生命周期记录；失败/取消的任务可在此跨重启恢复重试。"))

        filter_group = QGroupBox("任务状态筛选")
        filter_layout = QHBoxLayout(filter_group)
        filter_layout.addWidget(QLabel("按状态查看："))
        self.filter = QComboBox()
        for key, name in STATUS_LABELS.items():
            self.filter.addItem(name, key)
        self.filter.currentIndexChanged.connect(self.load)
        filter_layout.addWidget(self.filter)
        filter_layout.addStretch()
        self.refresh_btn = QPushButton("刷新列表")
        self.refresh_btn.clicked.connect(self.load)
        self.retry_btn = QPushButton("重试选中任务")
        self.retry_btn.clicked.connect(self.retry_selected)
        filter_layout.addWidget(self.refresh_btn)
        filter_layout.addWidget(self.retry_btn)
        layout.addWidget(filter_group)

        split = QSplitter(Qt.Orientation.Vertical)
        table_group = QGroupBox("历史记录")
        table_layout = QVBoxLayout(table_group)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["任务ID", "类型", "状态", "进度", "创建时间", "完成时间"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        table_layout.addWidget(self.table)
        split.addWidget(table_group)

        detail_group = QGroupBox("任务详情")
        detail_layout = QVBoxLayout(detail_group)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("点击上方任意一条任务，这里显示它的完整参数、进度与错误信息。")
        detail_layout.addWidget(self.detail)
        split.addWidget(detail_group)
        split.setSizes([380, 260])
        layout.addWidget(split, 1)
        QTimer.singleShot(0, self.load)

    def load(self):
        if not self.repo:
            return
        status = self.filter.currentData()
        rows = self.repo.list(200, 0, "1=1" if status in (None, "全部") else "status=?",
                              () if status in (None, "全部") else (status,), "created_at DESC")
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            vals = [r.get("id", ""), r.get("task_type", ""), r.get("status", ""),
                    f"{float(r.get('progress') or 0):.0f}%", r.get("created_at", ""), r.get("finished_at", "")]
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(str(v)))
            self.table.item(i, 0).setData(32, r)
        self.table.resizeColumnsToContents()

    def showEvent(self, event):
        super().showEvent(event)
        self.load()

    def show_detail(self):
        items = self.table.selectedItems()
        if not items:
            return
        r = self.table.item(items[0].row(), 0).data(32) or {}
        lines = []
        for k in ("id", "task_type", "status", "progress", "retry_count", "created_at", "started_at", "finished_at", "error_message"):
            lines.append(f"{k}: {r.get(k) or ''}")
        for k in ("input_data", "result_data"):
            try:
                val = json.dumps(json.loads(r.get(k) or "{}"), ensure_ascii=False, indent=2)
            except Exception:
                val = r.get(k) or ""
            lines.append(f"\n{k}:\n{val}")
        self.detail.setPlainText("\n".join(lines))

    def retry_selected(self):
        items = self.table.selectedItems()
        if not items or not self.task_service:
            return
        row = self.table.item(items[0].row(), 0).data(32) or {}
        if row.get("status") not in ("failed", "cancelled"):
            QMessageBox.information(self, "提示", "只有失败或已取消的任务可以重试。")
            return
        try:
            if self.task_manager:
                try:
                    self.task_manager.retry_registered(row.get("id"))
                except ValueError as exc:
                    if "执行器已失效" not in str(exc) or not self.collector_service:
                        raise
                    self.task_manager.recover_persisted_collection_task(row.get("id"), self.collector_service)
                message = "任务已重新提交执行。"
            else:
                self.task_service.retry_task(row.get("id"))
                message = "任务已重置为 pending。\n当前页面未连接任务执行器，需从采集中心重新提交。"
            self.load()
            self.detail.setPlainText(message)
        except Exception as exc:
            QMessageBox.warning(self, "重试失败", str(exc))
