import os
import sys
import ctypes
import ctypes.wintypes
import logging
from typing import Optional, Tuple

DESKTOP_NAME = "TIMI_GHOST"
WINSTA_NAME = "WinSta0"
FULL_DESKTOP_PATH = f"{WINSTA_NAME}\\{DESKTOP_NAME}"

GENERIC_ALL = 0x10000000

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

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

def ensure_ghost_desktop() -> Tuple[bool, Optional[int]]:
    try:
        h_winsta = user32.OpenWindowStationW(WINSTA_NAME, False, GENERIC_ALL)
        if h_winsta:
            user32.SetProcessWindowStation(h_winsta)
            
        h_desk = user32.OpenDesktopW(DESKTOP_NAME, 0, False, GENERIC_ALL)
        if not h_desk:
            h_desk = user32.CreateDesktopW(
                DESKTOP_NAME,
                None,
                None,
                0,
                GENERIC_ALL,
                None
            )
        if h_desk:
            return True, h_desk
        return False, None
    except Exception as e:
        logging.error(f"Error accessing {FULL_DESKTOP_PATH}: {e}")
        return False, None

def set_thread_to_ghost_desktop(h_desk: Optional[int] = None) -> bool:
    if h_desk is None:
        ok, h_desk = ensure_ghost_desktop()
        if not ok or not h_desk:
            return False
    return bool(user32.SetThreadDesktop(h_desk))
