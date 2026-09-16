from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ModelCenterNav(QObject):
    """全局导航信号：任意页面在缺少模型配置时可请求跳转到模型中心。"""

    request_open = Signal()


nav = ModelCenterNav()


def is_model_missing(message) -> bool:
    text = str(message or "")
    return ("模型中心" in text) or ("默认模型" in text) or ("默认 LLM" in text)


def offer_model_center(parent, message) -> bool:
    """弹出「去模型中心设置」提示；用户确认则请求跳转，返回是否跳转。"""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle("需要先配置模型")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(str(message))
    box.setInformativeText("点击「去模型中心设置」可直接打开模型中心，测试连接后选择模型设为默认即可。")
    goto = box.addButton("去模型中心设置", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is goto:
        nav.request_open.emit()
        return True
    return False
