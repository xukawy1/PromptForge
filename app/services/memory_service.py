from __future__ import annotations

import ctypes
import gc
import sys

from ctypes import wintypes


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _get_process_memory_info():
    """返回 (是否成功, PROCESS_MEMORY_COUNTERS)。"""
    if sys.platform != "win32":
        return False, None
    try:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
        func = ctypes.windll.psapi.GetProcessMemoryInfo
        func.restype = ctypes.c_int
        func.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if func(handle, ctypes.byref(counters), counters.cb):
            return True, counters
    except Exception:
        pass
    return False, None


def working_set_mb() -> float:
    """当前进程物理内存占用（MB）；不可用时返回 0。"""
    ok, counters = _get_process_memory_info()
    if ok and counters is not None:
        return counters.WorkingSetSize / (1024 * 1024)
    return 0.0


def release_memory() -> dict:
    """一键释放内存：Python 垃圾回收 + Qt 图片缓存 + 空闲 HTTP 连接。"""
    # 先导入/预热所需模块，避免统计口径被"首次导入"拉高
    try:
        from PySide6.QtGui import QPixmapCache
    except Exception:
        QPixmapCache = None
    try:
        from app.services.providers.ollama import OllamaProvider
    except Exception:
        OllamaProvider = None
    try:
        from app.services.providers.openai_compat import OpenAICompatProvider
    except Exception:
        OpenAICompatProvider = None
    gc.collect()
    before = working_set_mb()
    gc.collect()
    if QPixmapCache is not None:
        try:
            QPixmapCache.clear()
        except Exception:
            pass
    if OllamaProvider is not None:
        OllamaProvider.close_shared_clients()
    if OpenAICompatProvider is not None:
        OpenAICompatProvider.close_shared_clients()
    gc.collect()
    # Windows：主动收缩进程工作集，把闲置内存归还系统（任务管理器占用会明显下降）
    if sys.platform == "win32":
        try:
            func = ctypes.windll.psapi.EmptyWorkingSet
            func.restype = ctypes.c_int
            func.argtypes = [wintypes.HANDLE]
            func(ctypes.windll.kernel32.GetCurrentProcess())
        except Exception:
            pass
    after = working_set_mb()
    return {
        "before_mb": round(before, 1),
        "after_mb": round(after, 1),
        "freed_mb": round(max(0.0, before - after), 1),
    }
