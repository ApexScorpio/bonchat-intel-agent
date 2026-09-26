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

    def find_bonchat_window(self, auto_launch: bool = True) -> Optional[int]:
        """
        Locates the BonChat window reliably on TIMI_GHOST desktop.
        """
        from .desktop_isolation import get_ghost_windows, launch_process_on_ghost_desktop

        # 1. Enumerate windows directly on TIMI_GHOST
        ghost_wins = get_ghost_windows()
        for w in ghost_wins:
            t = w.get("title", "").lower()
            c = w.get("class", "").lower()
            if "bonchat" in t or "bonchat" in c or "ajuda" in t:
                self.hwnd = w["hwnd"]
                self.is_ghost = True
                logger.info(f"Found BonChat on TIMI_GHOST: HWND {self.hwnd} ('{w.get('title')}')")
                return self.hwnd

        # 2. Check active slot metadata as fallback
        slot_meta = r"C:\Users\lopes\.gemini\antigravity-ide\scratch\TIMI-ativador-repo\_runtime\slots\bonchat.json"
        if os.path.exists(slot_meta):
            try:
                with open(slot_meta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    h = data.get("hwnd")
                    if h and user32.IsWindow(h):
                        self.hwnd = int(h)
                        self.is_ghost = True
                        logger.info(f"Adopted BonChat from runtime slot: HWND {self.hwnd}")
                        return self.hwnd
            except Exception as e:
                logger.debug(f"Slot read check note: {e}")

        # 3. Auto-launch BonChat on TIMI_GHOST desktop if not running
        if auto_launch:
            bonchat_exe = r"S:\Users\lopes\AppData\Roaming\BonChat\BonChat.exe"
            if os.path.exists(bonchat_exe):
                logger.info("BonChat not running. Launching BonChat on TIMI_GHOST desktop...")
                pid = launch_process_on_ghost_desktop(bonchat_exe)
                logger.info(f"Launched BonChat with PID {pid}. Waiting for window to register...")
                for attempt in range(12):
                    time.sleep(1.0)
                    ghost_wins = get_ghost_windows()
                    for w in ghost_wins:
                        t = w.get("title", "").lower()
                        c = w.get("class", "").lower()
                        if "bonchat" in t or "bonchat" in c or "ajuda" in t:
                            self.hwnd = w["hwnd"]
                            self.is_ghost = True
                            logger.info(f"BonChat window detected: HWND {self.hwnd} ('{w.get('title')}')")
                            return self.hwnd

        logger.warning("BonChat window not found on TIMI_GHOST.")
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
        set_thread_to_ghost_desktop()
        lp = (int(y) << 16) | (int(x) & 0xFFFF)
        # WM_LBUTTONDOWN = 0x0201, MK_LBUTTON = 0x0001
        user32.PostMessageW(self.hwnd, 0x0201, 0x0001, lp)
        time.sleep(0.06)
        # WM_LBUTTONUP = 0x0202
        user32.PostMessageW(self.hwnd, 0x0202, 0, lp)
        time.sleep(0.2)

    def clear_search_bar(self):
        """Ensures search box is empty so all sidebar chats are visible."""
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        self.click_window(208, 95)
        time.sleep(0.08)
        self.click_window(120, 95)
        time.sleep(0.05)
        for _ in range(4):
            user32.PostMessageW(self.hwnd, 0x0100, 0x08, 0)
            user32.PostMessageW(self.hwnd, 0x0101, 0x08, 0)
            time.sleep(0.03)
        time.sleep(0.2)

    def select_channel(self, channel_target: Dict[str, Any]) -> bool:
        """
        Navigates to a specific channel using lateral sidebar visual template matching
        or calibrated coordinates. Never uses the search box to find groups.
        """
        canonical = channel_target.get("canonical_name", "")
        default_y = channel_target.get("default_y")
        template_name = channel_target.get("template_name")

        # 1. Always ensure search box is cleared so full lateral sidebar is shown
        self.clear_search_bar()

        # 2. Visual template matching on sidebar ROI
        full_img = self.capture_window()
        if full_img and (template_name or canonical):
            try:
                import cv2
                import numpy as np

                src_tpl_dir = os.path.join(os.path.dirname(__file__), "templates")
                data_tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "templates")

                tpl_filename = None
                if template_name:
                    tpl_filename = template_name
                else:
                    c_low = canonical.lower()
                    tpl_map = {
                        "theodore": "theodore.png",
                        "teodoro": "theodore.png",
                        "68": "timi_68.png",
                        "news": "timi_news.png",
                        "08": "timi_08.png"
                    }
                    for k, v in tpl_map.items():
                        if k in c_low:
                            tpl_filename = v
                            break

                tpl_file = None
                if tpl_filename:
                    for d in [src_tpl_dir, data_tpl_dir]:
                        p = os.path.join(d, tpl_filename)
                        if os.path.exists(p):
                            tpl_file = p
                            break

                if tpl_file and os.path.exists(tpl_file):
                    cv_img = cv2.cvtColor(np.array(full_img), cv2.COLOR_RGB2BGR)
                    search_roi = cv_img[100:750, 30:220]
                    tpl = cv2.imread(tpl_file)
                    if tpl is not None:
                        res = cv2.matchTemplate(search_roi, tpl, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val >= 0.80:
                            target_x = 30 + max_loc[0] + tpl.shape[1] // 2 + 40
                            target_y = 100 + max_loc[1] + tpl.shape[0] // 2
                            logger.info(f"Visual match for '{canonical}' ({os.path.basename(tpl_file)}) at (X={target_x}, Y={target_y}) conf={max_val:.2f}")
                            self.click_window(target_x, target_y)
                            time.sleep(0.8)
                            return True
                        else:
                            logger.debug(f"Template match for '{canonical}' below threshold: conf={max_val:.2f}")
            except Exception as e:
                logger.debug(f"Visual matching note: {e}")

        # 3. Fallback to calibrated coordinate
        if default_y:
            logger.info(f"Selecting '{canonical}' at calibrated sidebar Y={default_y}")
            self.click_window(150, default_y)
            time.sleep(0.8)
            return True

        logger.warning(f"Could not locate channel '{canonical}' on lateral sidebar.")
        return False

    def scroll_chat_up(self, notches: int = 5):
        """Scrolls the chat pane up to reveal earlier messages."""
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        # Ensure chat pane has focus
        self.click_window(600, 500)
        time.sleep(0.08)
        # Send Page Up key (VK_PRIOR = 0x21) to scroll by pages
        for _ in range(notches):
            user32.PostMessageW(self.hwnd, 0x0100, 0x21, 0) # WM_KEYDOWN
            time.sleep(0.04)
            user32.PostMessageW(self.hwnd, 0x0101, 0x21, 0) # WM_KEYUP
            time.sleep(0.15)

    def scan_channel_incremental(
        self,
        channel_canonical: str,
        watermark_tracker,
        max_scroll_passes: int = 15
    ) -> List[Image.Image]:
        """
        Deep scrolls upwards through group messages looking for important announcements,
        but stops immediately once it hits messages or frames that were already read in a previous scan.
        """
        unprocessed_frames: List[Image.Image] = []
        collected_signatures: List[str] = []
        collected_frame_hashes: List[str] = []

        logger.info(f"Beginning incremental scroll scan for '{channel_canonical}' (max_passes={max_scroll_passes})...")

        for pass_idx in range(max_scroll_passes):
            full_img = self.capture_window()
            if not full_img:
                logger.warning("Could not capture window during scroll.")
                break

            w, h = full_img.size
            chat_pane = full_img.crop((310, 45, min(w, 1300), h - 70))
            frame_hash = watermark_tracker.compute_frame_hash(chat_pane)

            # Quick local OCR (zero AI tokens) to check for message signatures
            try:
                quick_text = pytesseract.image_to_string(chat_pane, lang='por+eng', config='--psm 6')
            except Exception:
                quick_text = ""

            visible_messages = watermark_tracker.parse_chat_messages(quick_text)

            # Check if this frame hits the previous scan's watermark with anti-false-positive checks
            reached, reason = watermark_tracker.is_watermark_reached(channel_canonical, visible_messages, frame_hash)
            if reached:
                logger.info(
                    f"🛑 [WATERMARK CHECKPOINT] Atingido o limite da leitura anterior no passo {pass_idx+1} ({reason})! "
                    f"Parando scroll — mensagens anteriores já foram lidas."
                )
                break

            # Frame is new: store for analysis
            unprocessed_frames.append(chat_pane)
            collected_signatures.extend(visible_messages)
            collected_frame_hashes.append(frame_hash)

            if pass_idx < max_scroll_passes - 1:
                # Scroll chat upwards to reveal older messages
                self.scroll_chat_up(notches=5)
                time.sleep(0.4)

        # Update and persist watermark with newly seen messages and hashes
        if collected_signatures or collected_frame_hashes:
            watermark_tracker.commit_channel_watermark(
                channel_canonical,
                collected_signatures,
                collected_frame_hashes
            )

        logger.info(
            f"Finished incremental scan for '{channel_canonical}': "
            f"captured {len(unprocessed_frames)} new frame(s) to analyze."
        )
        return unprocessed_frames
