import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
)


class RecoveryPanel(QFrame):
    """Phase 3.19：启动恢复任务提示面板，展示中断任务并支持跨重启恢复。"""
    def __init__(self, task_service=None, task_manager=None, collector_service=None):
        super().__init__()
        self.task_service = task_service
        self.task_manager = task_manager
        self.collector_service = collector_service
        self.dismissed = False
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("任务恢复")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        self.summary = QLabel("")
        self.summary.setObjectName("panelHint")
        head.addWidget(self.summary)
        head.addStretch()
        layout.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['任务ID', '任务/操作', '状态', '重试次数', '可否恢复'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(150)
        layout.addWidget(self.table)
        foot = QHBoxLayout()
        self.recover_one = QPushButton('恢复选中任务')
        self.recover_one.clicked.connect(self.recover_selected)
        self.recover_all = QPushButton('全部恢复')
        self.recover_all.clicked.connect(self.recover_everything)
        self.ignore = QPushButton('忽略')
        self.ignore.clicked.connect(self.dismiss)
        foot.addWidget(self.recover_one); foot.addWidget(self.recover_all); foot.addWidget(self.ignore); foot.addStretch()
        layout.addLayout(foot)
        self.result = QLabel("")
        self.result.setObjectName("panelHint")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.refresh()

    def refresh(self):
        if not self.task_service:
            self.setVisible(False); return
        interrupted = self.task_service.list_interrupted_tasks()
        restorable = self.task_service.list_restorable_collection_tasks()
        restorable_ids = {r.get("id") for r in restorable}
        if self.dismissed or (not interrupted and not restorable):
            self.setVisible(False); return
        self.setVisible(True)
        # 表格显示"全部中断任务"：过去只列可恢复的采集任务，于是出现
        # "上面提示有 N 个中断、下面列表却是空的"（skill 扩写/生成/翻译等非采集任务没有执行计划，全被过滤掉）
        rows, seen = [], set()
        for r in list(restorable) + list(interrupted):
            rid = r.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            rows.append(r)
        self._restorable_ids = restorable_ids
        self.summary.setText(f"上次中断任务：{len(rows)}    其中可一键恢复：{len(restorable)}")
        self.table.setRowCount(0)
        for r in rows:
            i = self.table.rowCount(); self.table.insertRow(i)
            payload = r.get("input_payload")
            if not isinstance(payload, dict):
                try:
                    payload = json.loads(r.get("input_data") or "{}")
                except (TypeError, ValueError):
                    payload = {}
            plan = payload.get("execution_plan") or {}
            label = plan.get("operation") or r.get("task_type") or ""
            can_recover = "可恢复" if r.get("id") in restorable_ids else "仅记录（需重做）"
            vals = [r.get('id', ''), label, r.get('status', ''), str(r.get('retry_count') or 0), can_recover]
            for c, v in enumerate(vals): self.table.setItem(i, c, QTableWidgetItem(str(v)))
            self.table.item(i, 0).setData(32, r)
        self.table.resizeColumnsToContents()
        can_recover = bool(self.task_manager and self.collector_service)
        self.recover_one.setEnabled(can_recover and bool(restorable))
        self.recover_all.setEnabled(can_recover and bool(restorable))
        if not can_recover:
            self.result.setText("当前未连接任务执行器，可在历史记录页手动重试。")
        elif not restorable:
            self.result.setText("以上任务属于 skill 扩写/生成/翻译等类型，没有可续跑的执行计划——"
                                "请到对应页面重新执行，或到「历史记录」页删除这些记录。")

    def _recover_rows(self, rows):
        recovered, errors = [], []
        for row in rows:
            task_id = row.get("id")
            try:
                self.task_manager.recover_persisted_collection_task(task_id, self.collector_service)
                recovered.append(task_id)
            except Exception as exc:
                errors.append(f"{task_id}: {exc}")
        parts = [f"已恢复 {len(recovered)} 个任务。"] if recovered else []
        if errors: parts.append("失败 " + str(len(errors)) + " 个：" + "；".join(errors[:3]))
        self.result.setText(" ".join(parts) if parts else "没有可恢复的任务。")
        self.refresh()

    def recover_selected(self):
        items = self.table.selectedItems()
        if not items:
            self.result.setText("请先在列表中选择一个任务。"); return
        row = self.table.item(items[0].row(), 0).data(32) or {}
        if row.get("id") not in getattr(self, "_restorable_ids", set()):
            kind = row.get("task_type") or "该任务"
            self.result.setText(f"「{kind}」没有可续跑的执行计划，无法自动恢复——"
                                "请到对应页面重新执行，或到「历史记录」页删除这条记录。")
            return
        self._recover_rows([row])

    def recover_everything(self):
        if not self.task_service: return
        self._recover_rows(self.task_service.list_restorable_collection_tasks())

    def dismiss(self):
        self.dismissed = True
        self.setVisible(False)


class DashboardPage(QWidget):
    def __init__(self, service=None, task_service=None, task_manager=None, collector_service=None):
        super().__init__(); self.service = service; self.cards = {}
        layout = QVBoxLayout(self)
        title = QLabel("工作台"); title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("PromptForge 数据总览"); subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)
        grid = QGridLayout(); grid.setSpacing(12)
        items = [("sources","资料来源"),("documents","文档"),("images","图片"),("prompts","Prompt"),("prompt_components","组件"),("prompt_templates","模板"),("knowledge_items","知识"),("generation_history","生成记录")]
        for i,(key,name) in enumerate(items):
            card=QFrame(); card.setProperty("card", True); card.setFrameShape(QFrame.StyledPanel); box=QVBoxLayout(card)
            n=QLabel("0"); n.setStyleSheet("font-size:26px;font-weight:700;"); box.addWidget(n)
            name_label = QLabel(name); name_label.setObjectName("panelHint"); box.addWidget(name_label)
            self.cards[key]=n; grid.addWidget(card,i//4,i%4)
        layout.addLayout(grid)
        self.recovery_panel = RecoveryPanel(task_service=task_service, task_manager=task_manager, collector_service=collector_service)
        layout.addWidget(self.recovery_panel)
        status_row = QHBoxLayout()
        self.status = QLabel("数据库已连接"); status_row.addWidget(self.status)
        status_row.addStretch()
        release_btn = QPushButton("一键释放内存")
        release_btn.setToolTip("清理缓存与空闲连接，释放占用的物理内存（不影响已打开的功能）")
        release_btn.clicked.connect(self.release_memory)
        status_row.addWidget(release_btn)
        refresh_btn = QPushButton("刷新统计")
        refresh_btn.clicked.connect(self.refresh)
        status_row.addWidget(refresh_btn)
        layout.addLayout(status_row)
        layout.addStretch(); self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        # 每次切换到工作台自动刷新统计，保证数据实时。
        self.refresh()

    def release_memory(self):
        from app.services.memory_service import release_memory
        from PySide6.QtWidgets import QMessageBox
        outcome = release_memory()
        QMessageBox.information(
            self, "内存已释放",
            f"释放前占用：{outcome['before_mb']} MB\n释放后占用：{outcome['after_mb']} MB\n已释放：{outcome['freed_mb']} MB\n\n"
            "已清理 Python 缓存、界面图片缓存与空闲网络连接；不影响已打开的功能。")
        self.refresh()

    def refresh(self):
        if not self.service: return
        stats=self.service.stats()
        for key,label in self.cards.items(): label.setText(str(stats.get(key,0)))
        self.status.setText(f"当前待处理任务：{stats.get('pending_tasks',0)}")
        self.recovery_panel.refresh()
