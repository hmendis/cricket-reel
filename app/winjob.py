"""Tie every child process (FFmpeg, FFprobe) to the app's lifetime on Windows.

The app process joins a Windows Job Object with "kill on job close". Child processes join it automatically, and
when the app ends for any reason (window closed, crash, ended in Task Manager, start.bat window closed) Windows
closes the job and ends every process still in it. Without this a cancelled or orphaned full-length transcode
could keep running and keep the match files locked.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
_job_handle = None  # kept open for the life of the process; Windows closes it at exit


def attach() -> bool:
    """Put this process (and so all its future children) in a kill-on-close job. Returns True if done."""
    global _job_handle
    if os.name != "nt" or _job_handle is not None:
        return _job_handle is not None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                       "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    KILL_ON_JOB_CLOSE, BREAKAWAY_OK, EXTENDED_LIMIT_INFORMATION = 0x2000, 0x800, 9
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        log.warning("CreateJobObject failed: %s", ctypes.get_last_error())
        return False
    info = EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = KILL_ON_JOB_CLOSE | BREAKAWAY_OK
    if not k32.SetInformationJobObject(job, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
        log.warning("SetInformationJobObject failed: %s", ctypes.get_last_error())
        k32.CloseHandle(job)
        return False
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        log.warning("AssignProcessToJobObject failed: %s", ctypes.get_last_error())
        k32.CloseHandle(job)
        return False
    _job_handle = job
    return True
