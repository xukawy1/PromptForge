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
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['任务ID', '采集操作', '状态', '重试次数'])
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
        if self.dismissed or (not interrupted and not restorable):
            self.setVisible(False); return
        self.setVisible(True)
        self.summary.setText(f"上次中断任务：{len(interrupted)}    可恢复采集任务：{len(restorable)}")
        self.table.setRowCount(0)
        for r in restorable:
            i = self.table.rowCount(); self.table.insertRow(i)
            payload = r.get("input_payload") or {}
            operation = (payload.get("execution_plan") or {}).get("operation", "")
            vals = [r.get('id', ''), operation, r.get('status', ''), str(r.get('retry_count') or 0)]
            for c, v in enumerate(vals): self.table.setItem(i, c, QTableWidgetItem(str(v)))
            self.table.item(i, 0).setData(32, r)
        self.table.resizeColumnsToContents()
        can_recover = bool(self.task_manager and self.collector_service)
        self.recover_one.setEnabled(can_recover); self.recover_all.setEnabled(can_recover)
        if not can_recover:
            self.result.setText("当前未连接任务执行器，可在历史记录页手动重试。")

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
        refresh_btn = QPushButton("刷新统计")
        refresh_btn.clicked.connect(self.refresh)
        status_row.addWidget(refresh_btn)
        layout.addLayout(status_row)
        layout.addStretch(); self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        # 每次切换到工作台自动刷新统计，保证数据实时。
        self.refresh()

    def refresh(self):
        if not self.service: return
        stats=self.service.stats()
        for key,label in self.cards.items(): label.setText(str(stats.get(key,0)))
        self.status.setText(f"当前待处理任务：{stats.get('pending_tasks',0)}")
        self.recovery_panel.refresh()
