import os
import time
import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
import ctypes
import ctypes.wintypes
import win32gui
import win32con
import win32process
import win32api
from PIL import Image, ImageOps, ImageFilter
import pytesseract

from .desktop_isolation import (
    set_thread_to_ghost_desktop,
    open_ghost_desktop_handle,
    get_current_desktop_name,
)

logger = logging.getLogger("BonChatReader")

user32 = ctypes.windll.user32

class BonChatReader:
    def __init__(self, tesseract_cmd: Optional[str] = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.hwnd: Optional[int] = None
        self.is_ghost: bool = False

    def find_bonchat_window(self) -> Optional[int]:
        """
        Locates the BonChat window reliably across desktops.
        """
        # 1. Quick check active telemetry slot metadata if available
        slot_meta = r"C:\Users\lopes\.gemini\antigravity-ide\scratch\TIMI-ativador-repo\_runtime\slots\bonchat.json"
        if os.path.exists(slot_meta):
            try:
                with open(slot_meta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    h = data.get("hwnd")
                    if h and win32gui.IsWindow(h):
                        self.hwnd = int(h)
                        self.is_ghost = True
                        logger.info(f"Adopted BonChat from runtime slot: HWND {self.hwnd}")
                        return self.hwnd
            except Exception as e:
                logger.debug(f"Slot read check note: {e}")

        # 2. Enumerate windows directly on TIMI_GHOST desktop handle
        h_desk = open_ghost_desktop_handle()
        if h_desk:
            cb_t = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            candidates = []

            def cb(h, _):
                if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                    title = (win32gui.GetWindowText(h) or "").strip()
                    wr = win32gui.GetWindowRect(h)
                    w, h_dim = wr[2] - wr[0], wr[3] - wr[1]
                    if "bonchat" in title.lower() and w >= 300 and h_dim >= 300:
                        candidates.append(int(h))
                return True

            callback = cb_t(cb)
            user32.EnumDesktopWindows(h_desk, callback, 0)
            user32.CloseDesktop(h_desk)

            if candidates:
                self.hwnd = candidates[0]
                self.is_ghost = True
                logger.info(f"Found BonChat on TIMI_GHOST via EnumDesktopWindows: HWND {self.hwnd}")
                return self.hwnd

        # 3. Fallback check active desktop
        def def_cb(h, _):
            if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h) and not win32gui.IsIconic(h):
                title = (win32gui.GetWindowText(h) or "").strip()
                if "bonchat" in title.lower():
                    wr = win32gui.GetWindowRect(h)
                    if (wr[2] - wr[0] >= 300) and (wr[3] - wr[1] >= 300):
                        self.hwnd = int(h)
                        self.is_ghost = False
            return True

        win32gui.EnumWindows(def_cb, None)
        if self.hwnd:
            logger.info(f"Found BonChat on active desktop: HWND {self.hwnd}")
            return self.hwnd

        logger.warning("BonChat window not found.")
        return None

    def capture_window(self) -> Optional[Image.Image]:
        """Captures the BonChat window buffer without stealing focus."""
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            if not self.find_bonchat_window():
                return None

        # Ensure calling thread is attached to ghost desktop before drawing
        set_thread_to_ghost_desktop()

        try:
            wr = win32gui.GetWindowRect(self.hwnd)
            w, h = wr[2] - wr[0], wr[3] - wr[1]
            if w < 100 or h < 100:
                return None

            import win32ui
            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            save_bit_map = win32ui.CreateBitmap()
            save_bit_map.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(save_bit_map)

            # PW_RENDERFULLCONTENT = 2
            result = ctypes.windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 2)
            if not result:
                result = ctypes.windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), 0)
            if not result:
                save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), 0x00CC0020)

            bmp_info = save_bit_map.GetInfo()
            bmp_str = save_bit_map.GetBitmapBits(True)
            img = Image.frombuffer('RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']), bmp_str, 'raw', 'BGRX', 0, 1)

            win32gui.DeleteObject(save_bit_map.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            return img
        except Exception as e:
            logger.error(f"Error capturing window: {e}")
            return None

    def click_window(self, x: int, y: int):
        """Sends background mouse click to window relative coordinates."""
        if not self.hwnd:
            return
        lp = win32api.MAKELONG(int(x), int(y))
        win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
        time.sleep(0.06)
        win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lp)
        time.sleep(0.2)

    def select_channel(self, channel_target: Dict[str, Any]) -> bool:
        """
        Navigates to a specific channel using calibrated visual coordinates or search.
        """
        canonical = channel_target.get("canonical_name", "")
        default_y = channel_target.get("default_y")
        search_term = channel_target.get("search_term")

        # 1. Direct calibrated click
        if default_y:
            logger.info(f"Selecting '{canonical}' at calibrated sidebar Y={default_y}")
            self.click_window(180, default_y)
            time.sleep(0.8)
            return True

        # 2. Search box lookup
        if search_term:
            logger.info(f"Searching channel via search bar: '{search_term}'")
            # Click search input
            self.click_window(180, 100)
            time.sleep(0.2)

            # Select all and delete previous query
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_CONTROL, 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, ord('A'), 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, ord('A'), 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_CONTROL, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_BACK, 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_BACK, 0)
            time.sleep(0.1)

            # Type search term
            for ch in search_term:
                win32gui.PostMessage(self.hwnd, win32con.WM_CHAR, ord(ch), 0)
                time.sleep(0.04)
            time.sleep(0.6)

            # Click top search result (Y ~160)
            self.click_window(180, 160)
            time.sleep(0.8)

            # Clear search
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
            return True

        return False

    def capture_chat_images(self, scroll_passes: int = 2) -> List[Image.Image]:
        """
        Captures the visual chat pane (including flyers, posters, pinned banners)
        so it can be directly analyzed with Gemini Multimodal Vision.
        """
        images = []
        for p in range(scroll_passes):
            full_img = self.capture_window()
            if not full_img:
                break
            w, h = full_img.size
            # Crop chat pane (X: 310 to 1250, Y: 45 to h - 70)
            chat_pane = full_img.crop((310, 45, min(w, 1300), h - 70))
            images.append(chat_pane)

            if p < scroll_passes - 1:
                # Scroll chat up slightly to see earlier announcements
                chat_x = int(w * 0.65)
                chat_y = int(h * 0.5)
                lp = win32api.MAKELONG(chat_x, chat_y)
                for _ in range(4):
                    win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEWHEEL, win32api.MAKELONG(0, 1200), lp)
                    time.sleep(0.1)
                time.sleep(0.5)

        return images
