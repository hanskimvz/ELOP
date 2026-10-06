"""Windows timing helpers (no-ops elsewhere)."""

import contextlib
import sys

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    import ctypes

    _winmm = ctypes.WinDLL("winmm")
    _kernel32 = ctypes.WinDLL("kernel32")
    _kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    _kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    _kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

HIGH_PRIORITY_CLASS = 0x00000080


@contextlib.contextmanager
def timing_context(high_priority: bool = True):
    """1 ms OS timer resolution and (optionally) high process priority.

    Windows의 기본 타이머 분해능(15.6 ms)은 sleep 간격과 스레드 깨어남 지터를 키운다.
    """
    if not _IS_WIN:
        yield
        return

    _winmm.timeBeginPeriod(1)
    proc = _kernel32.GetCurrentProcess()
    old_class = _kernel32.GetPriorityClass(proc) if high_priority else 0
    if high_priority:
        _kernel32.SetPriorityClass(proc, HIGH_PRIORITY_CLASS)
    try:
        yield
    finally:
        if high_priority and old_class:
            _kernel32.SetPriorityClass(proc, old_class)
        _winmm.timeEndPeriod(1)
