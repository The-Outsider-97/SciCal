"""End the engine when the app that started it is gone, without ever touching standard input.

The first version watched for the end of standard input from a thread. On Windows that is a trap: while one thread is blocked reading a
pipe, every child process that inherits that pipe as its standard input hangs during its own start-up. The calculation workers and the
programs SLAI's agents start (GPU queries and the like) are such children, so nothing ever became ready. This module watches the
*processes* instead: the engine's parent, and on Windows the short chain above it (the venv's python.exe stub, the launcher, the app).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable


def _windows_ancestors(limit: int = 4) -> list[int]:
    """Process ids above this one, nearest first: up to and including the first that is not a Python or SciCal launcher (that one is the app)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    table: dict[int, tuple[int, str]] = {}
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[int(e.th32ProcessID)] = (int(e.th32ParentProcessID), str(e.szExeFile).lower())
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    out: list[int] = []
    pid = os.getpid()
    while len(out) < limit and pid in table:
        parent = table[pid][0]
        if parent in (0, pid) or parent not in table or parent in out:
            break
        out.append(parent)
        name = table[parent][1]
        if not (name.startswith("python") or name.startswith("scical-engine")):
            break                                           # that is the app itself; do not go on to the desktop shell
        pid = parent
    return out


def _windows_wait_any(pids: list[int]) -> None:
    """Block until one of the processes has ended."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
    k.WaitForMultipleObjects.restype = wintypes.DWORD
    handles = [h for h in (k.OpenProcess(0x00100000, False, p) for p in pids) if h]          # SYNCHRONIZE
    if not handles:
        raise OSError("no parent process could be opened")
    arr = (wintypes.HANDLE * len(handles))(*handles)
    while True:
        r = k.WaitForMultipleObjects(len(handles), arr, False, 0xFFFFFFFF)
        if r != 0x102:                                      # anything but a timeout: a process ended (or the wait failed; stop either way)
            return


def watch(on_gone: Callable[[], None]) -> threading.Thread:
    """Call `on_gone` once when the process that started this one (or, on Windows, the app above the launchers) has ended."""
    def run() -> None:
        try:
            if os.name == "nt":
                pids = _windows_ancestors()
                if not pids:
                    print("SciCal: could not find the app's process; the engine will not stop on its own.", file=sys.stderr, flush=True)
                    return
                _windows_wait_any(pids)
            else:
                parent = os.getppid()
                while os.getppid() == parent:
                    time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001 - never take the engine down because the watch failed
            print(f"SciCal: the parent watch failed ({type(exc).__name__}: {exc}); the engine will not stop on its own.", file=sys.stderr, flush=True)
            return
        on_gone()
    t = threading.Thread(target=run, name="scical-parent-watch", daemon=True)
    t.start()
    return t
