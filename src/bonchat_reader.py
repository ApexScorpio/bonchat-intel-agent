import time
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
import ctypes
import ctypes.wintypes
import win32gui
import win32ui
import win32con
import win32process
import win32api
import psutil
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import pytesseract

from .desktop_isolation import (
    set_thread_to_ghost_desktop,
    get_current_desktop_name,
)

logger = logging.getLogger("BonChatReader")

class BonChatReader:
    def __init__(self, tesseract_cmd: Optional[str] = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.hwnd: Optional[int] = None
        self.is_ghost: bool = False

    def find_bonchat_window(self) -> Optional[int]:
        """
        Locates the BonChat window either on active desktop or TIMI_GHOST desktop.
        """
        candidates = []

        def enum_cb(h, _):
            if not win32gui.IsWindow(h) or not win32gui.IsWindowVisible(h) or win32gui.IsIconic(h):
                return True
            title = (win32gui.GetWindowText(h) or "").strip()
            if not title.lower().startswith("bonchat"):
                return True
            wr = win32gui.GetWindowRect(h)
            w, h_dim = wr[2] - wr[0], wr[3] - wr[1]
            if w < 300 or h_dim < 300:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(h)
                proc = psutil.Process(pid)
                if "bonchat" in proc.name().lower():
                    candidates.append(h)
            except Exception:
                pass
            return True

        # First check current desktop
        win32gui.EnumWindows(enum_cb, None)
        if candidates:
            self.hwnd = candidates[0]
            self.is_ghost = False
            logger.info(f"Found BonChat on active desktop: HWND {self.hwnd}")
            return self.hwnd

        # Next check TIMI_GHOST desktop
        if set_thread_to_ghost_desktop():
            candidates.clear()
            win32gui.EnumWindows(enum_cb, None)
            if candidates:
                self.hwnd = candidates[0]
                self.is_ghost = True
                logger.info(f"Found BonChat on TIMI_GHOST desktop: HWND {self.hwnd}")
                return self.hwnd

        logger.warning("BonChat window not found on any desktop.")
        return None

    def capture_window(self) -> Optional[Image.Image]:
        """Captures the BonChat window buffer without stealing focus."""
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):
            if not self.find_bonchat_window():
                return None

        try:
            wr = win32gui.GetWindowRect(self.hwnd)
            w, h = wr[2] - wr[0], wr[3] - wr[1]
            if w < 100 or h < 100:
                return None

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

    def scroll_chat(self, steps: int = 5, direction_up: bool = True):
        """Scrolls the chat pane up or down."""
        if not self.hwnd:
            return
        wr = win32gui.GetWindowRect(self.hwnd)
        w, h = wr[2] - wr[0], wr[3] - wr[1]
        chat_x = int(w * 0.65)
        chat_y = int(h * 0.5)
        lp = win32api.MAKELONG(chat_x, chat_y)
        delta = 1200 if direction_up else -1200

        for _ in range(steps):
            win32gui.PostMessage(self.hwnd, win32con.WM_MOUSEWHEEL, win32api.MAKELONG(0, delta), lp)
            time.sleep(0.12)

    def find_group_in_sidebar(self, target_name: str) -> Optional[Tuple[int, int]]:
        """
        Uses OCR on the sidebar to find the click coordinates for a given channel name.
        """
        img = self.capture_window()
        if not img:
            return None

        w, h = img.size
        sidebar_w = int(w * 0.35)
        sidebar = img.crop((0, 0, sidebar_w, h))

        # Enhance contrast for OCR
        gray = ImageOps.autocontrast(sidebar.convert("L"))
        sharpened = gray.filter(ImageFilter.SHARPEN)

        data = pytesseract.image_to_data(sharpened, output_type=pytesseract.Output.DICT)
        
        # Build lines of text with coordinates
        normalized_target = re.sub(r'[^a-zA-Z0-9]', '', target_name.lower())
        
        num_boxes = len(data['text'])
        for i in range(num_boxes):
            word = data['text'][i].strip()
            if not word:
                continue
            
            # Check single word or multi-word substring match
            norm_word = re.sub(r'[^a-zA-Z0-9]', '', word.lower())
            if len(norm_word) >= 3 and norm_word in normalized_target:
                x = data['left'][i] + data['width'][i] // 2
                y = data['top'][i] + data['height'][i] // 2
                # Ensure it's in the channel list area (not top header)
                if y > 80:
                    logger.info(f"Target '{target_name}' matched word '{word}' at ({x}, {y})")
                    return (x, y)

        return None

    def read_active_chat(self, scroll_passes: int = 3) -> str:
        """
        Reads all visible messages in the active chat pane, scrolling up to gather history.
        """
        collected_texts = []
        
        for p in range(scroll_passes):
            img = self.capture_window()
            if not img:
                break
            
            w, h = img.size
            chat_pane = img.crop((int(w * 0.35), 70, w, h - 80))
            
            # OCR chat area
            text = pytesseract.image_to_string(chat_pane, lang='por+eng')
            if text.strip():
                collected_texts.append(text)
            
            if p < scroll_passes - 1:
                self.scroll_chat(steps=4, direction_up=True)
                time.sleep(0.4)

        # Combine text while removing exact duplicate blocks
        all_text = "\n---\n".join(collected_texts)
        return all_text
