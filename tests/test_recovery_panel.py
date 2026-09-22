"""工作台「任务恢复」面板：中断任务必须在列表里显示出来。

回归背景：过去表格只列"可恢复的采集任务"，而提示里数的是"全部中断任务"，
于是强制断开 skill 扩写/生成/翻译 等任务后，重启会看到"上次中断任务：N"、下面列表却是空的。
"""


def _make_panel(task_service):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.pages.dashboard.page import RecoveryPanel
    return RecoveryPanel(task_service=task_service)


class FakeTaskService:
    interrupted = [
        {"id": "t-skill", "task_type": "skill.apply", "status": "failed", "retry_count": 0, "input_data": "{}"},
        {"id": "t-gen", "task_type": "generation.生成", "status": "failed", "retry_count": 1, "input_data": "{}"},
    ]
    restorable = [
        {"id": "t-col", "task_type": "collection.fetch", "status": "failed", "retry_count": 0,
         "input_payload": {"execution_plan": {"version": 1, "kind": "collector", "operation": "网页采集"}}},
    ]

    def list_interrupted_tasks(self, limit=200):
        return list(self.interrupted)

    def list_restorable_collection_tasks(self, limit=200):
        return list(self.restorable)


def test_recovery_panel_lists_all_interrupted_tasks():
    panel = _make_panel(FakeTaskService())
    assert panel.table.rowCount() == 3, "中断任务必须全部列出来，而不是只列可恢复的采集任务"

    ids = [panel.table.item(r, 0).text() for r in range(panel.table.rowCount())]
    assert {"t-skill", "t-gen", "t-col"} <= set(ids)

    flags = {panel.table.item(r, 0).text(): panel.table.item(r, 4).text() for r in range(panel.table.rowCount())}
    assert flags["t-col"] == "可恢复"
    assert "仅记录" in flags["t-skill"] and "仅记录" in flags["t-gen"]

    kinds = {panel.table.item(r, 0).text(): panel.table.item(r, 1).text() for r in range(panel.table.rowCount())}
    assert kinds["t-col"] == "网页采集"
    assert kinds["t-skill"] == "skill.apply"      # 没有执行计划时退回显示任务类型，而不是留空

    assert "上次中断任务：3" in panel.summary.text()
    assert "可一键恢复：1" in panel.summary.text()


def test_recovery_panel_disables_recover_without_executor():
    """没接任务执行器时（或没有可恢复任务时）恢复按钮禁用，并给出说明。"""
    panel = _make_panel(FakeTaskService())
    assert panel.recover_one.isEnabled() is False
    assert panel.recover_all.isEnabled() is False


def test_recovery_panel_hides_when_nothing_interrupted():
    class Empty:
        def list_interrupted_tasks(self, limit=200):
            return []

        def list_restorable_collection_tasks(self, limit=200):
            return []

    panel = _make_panel(Empty())
    assert panel.isVisible() is False
