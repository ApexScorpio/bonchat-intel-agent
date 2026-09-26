import os
import sys
import ctypes
import ctypes.wintypes
import subprocess
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

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.wintypes.DWORD),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.wintypes.DWORD),
        ("dwY", ctypes.wintypes.DWORD),
        ("dwXSize", ctypes.wintypes.DWORD),
        ("dwYSize", ctypes.wintypes.DWORD),
        ("dwXCountChars", ctypes.wintypes.DWORD),
        ("dwYCountChars", ctypes.wintypes.DWORD),
        ("dwFillAttribute", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("wShowWindow", ctypes.wintypes.WORD),
        ("cbReserved2", ctypes.wintypes.WORD),
        ("lpReserved2", ctypes.c_char_p),
        ("hStdInput", ctypes.wintypes.HANDLE),
        ("hStdOutput", ctypes.wintypes.HANDLE),
        ("hStdError", ctypes.wintypes.HANDLE),
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.wintypes.HANDLE),
        ("hThread", ctypes.wintypes.HANDLE),
        ("dwProcessId", ctypes.wintypes.DWORD),
        ("dwThreadId", ctypes.wintypes.DWORD),
    ]

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
        if not h_desk:
            h_desk = user32.CreateDesktopW(DESKTOP_NAME, None, None, 0, GENERIC_ALL, None)
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

def get_hwnd_desktop_name(hwnd: int) -> str:
    if not user32.IsWindow(hwnd):
        return "INVALID_HWND"
    pid = ctypes.wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not tid:
        return "DEFAULT"
    h_desk = user32.GetThreadDesktop(tid)
    return get_current_desktop_name(h_desk)

def launch_process_on_ghost_desktop(cmd: Any, cwd: Optional[str] = None) -> Optional[int]:
    """
    Launches a process natively with STARTUPINFO.lpDesktop = WinSta0\\TIMI_GHOST
    """
    open_ghost_desktop_handle()
    
    SW_SHOWNOACTIVATE = 4
    STARTF_USESHOWWINDOW = 0x00000001

    si_c = STARTUPINFO()
    si_c.cb = ctypes.sizeof(STARTUPINFO)
    si_c.lpDesktop = FULL_DESKTOP_PATH
    si_c.dwFlags = STARTF_USESHOWWINDOW
    si_c.wShowWindow = SW_SHOWNOACTIVATE

    pi_c = PROCESS_INFORMATION()

    if isinstance(cmd, list):
        cmd_str = subprocess.list2cmdline(cmd)
    else:
        cmd_str = str(cmd)

    cmd_buf = ctypes.create_unicode_buffer(cmd_str)

    created = kernel32.CreateProcessW(
        None,
        cmd_buf,
        None,
        None,
        False,
        0x08000000,  # CREATE_NO_WINDOW
        None,
        cwd,
        ctypes.byref(si_c),
        ctypes.byref(pi_c)
    )

    if created:
        pid = pi_c.dwProcessId
        kernel32.CloseHandle(pi_c.hThread)
        kernel32.CloseHandle(pi_c.hProcess)
        return pid
    else:
        err = kernel32.GetLastError()
        logging.error(f"Failed to create process on desktop {FULL_DESKTOP_PATH}: WinError {err}")
        return None

def get_ghost_windows() -> List[Dict[str, Any]]:
    """
    Enumerates all windows on TIMI_GHOST using direct C-types EnumDesktopWindows,
    avoiding the win32gui error 122 limitation.
    """
    cb_t = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    h_desk = open_ghost_desktop_handle()
    if not h_desk:
        return []

    found = []
    def cb(hwnd, _):
        if user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 200 and h > 200:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                found.append({
                    "hwnd": int(hwnd),
                    "pid": int(pid.value),
                    "title": buf.value,
                    "class": cls_buf.value,
                    "rect": (rect.left, rect.top, rect.right, rect.bottom),
                    "w": w,
                    "h": h
                })
        return True

    callback = cb_t(cb)
    user32.EnumDesktopWindows(h_desk, callback, 0)
    user32.CloseDesktop(h_desk)
    return found
