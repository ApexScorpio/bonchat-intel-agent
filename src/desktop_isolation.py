import os
import sys
import json
import ctypes
import ctypes.wintypes
import logging
from typing import Optional, Tuple, List, Dict, Any

DESKTOP_NAME = "TIMI_GHOST"
WINSTA_NAME = "WinSta0"
FULL_DESKTOP_PATH = f"{WINSTA_NAME}\\{DESKTOP_NAME}"

GENERIC_ALL = 0x10000000
DESKTOP_READOBJECTS = 0x0001
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenDesktopW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
user32.OpenDesktopW.restype = ctypes.wintypes.HANDLE

user32.CloseDesktop.argtypes = [ctypes.wintypes.HANDLE]
user32.CloseDesktop.restype = ctypes.wintypes.BOOL

user32.SetThreadDesktop.argtypes = [ctypes.wintypes.HANDLE]
user32.SetThreadDesktop.restype = ctypes.wintypes.BOOL

def get_current_desktop_name(h_desk: Optional[int] = None) -> str:
    if h_desk is None:
        h_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not h_desk:
        return "UNKNOWN"
    size = ctypes.wintypes.DWORD()
    buf = ctypes.create_unicode_buffer(256)
    res = user32.GetUserObjectInformationW(h_desk, 2, buf, ctypes.sizeof(buf), ctypes.byref(size))
    if res:
        return buf.value
    return "UNKNOWN"

def open_ghost_desktop_handle() -> Optional[int]:
    try:
        h_winsta = user32.OpenWindowStationW(WINSTA_NAME, False, GENERIC_ALL)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta)
            
        h_desk = user32.OpenDesktopW(DESKTOP_NAME, 0, False, 0x01FF)
        if not h_desk:
            h_desk = user32.OpenDesktopW(DESKTOP_NAME, 0, False, 0x41)
        return h_desk or None
    except Exception as e:
        logging.error(f"Error opening {FULL_DESKTOP_PATH}: {e}")
        return None

def set_thread_to_ghost_desktop() -> bool:
    h_desk = open_ghost_desktop_handle()
    if not h_desk:
        return False
    ok = bool(user32.SetThreadDesktop(h_desk))
    return ok
