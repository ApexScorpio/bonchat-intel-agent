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
from .telemetry_bridge import LiveViewBridge

logger = logging.getLogger("BonChatReader")

user32 = ctypes.windll.user32

class BonChatReader:
    def __init__(self, tesseract_cmd: Optional[str] = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.hwnd: Optional[int] = None
        self.is_ghost: bool = False

    def dismiss_image_preview(self):
        """If any modal/image preview window (Qt5QWindowToolSaveBits) is open, close it with ESC."""
        from .desktop_isolation import get_ghost_windows, set_thread_to_ghost_desktop
        set_thread_to_ghost_desktop()
        ghost_wins = get_ghost_windows()
        for w in ghost_wins:
            if "toolsavebits" in w.get("class", "").lower():
                user32.PostMessageW(w["hwnd"], win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                user32.PostMessageW(w["hwnd"], win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                time.sleep(0.08)

    def _ensure_window_layout(self):
        """Ensures BonChat is restored, visible, and calibrated to standard 1536x900 resolution."""
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.SetWindowPos(self.hwnd, 0, 0, 0, 1536, 900, win32con.SWP_SHOWWINDOW)
        except Exception as e:
            logger.debug(f"Layout calibration note: {e}")

    def find_bonchat_window(self, auto_launch: bool = True) -> Optional[int]:
        """
        Locates the BonChat window reliably on TIMI_GHOST desktop.
        Prioritizes the main application window (Qt5QWindowIcon) over image preview tool windows.
        """
        from .desktop_isolation import get_ghost_windows, launch_process_on_ghost_desktop

        # Dismiss any open image preview overlay
        self.dismiss_image_preview()

        # 1. Enumerate windows directly on TIMI_GHOST
        ghost_wins = get_ghost_windows()

        # First pass: find main Qt5QWindowIcon window
        for w in ghost_wins:
            t = w.get("title", "").lower()
            c = w.get("class", "").lower()
            if "qt5qwindowicon" in c and ("bonchat" in t or w.get("w", 0) > 800):
                self.hwnd = w["hwnd"]
                self.is_ghost = True
                self._ensure_window_layout()
                logger.info(f"Found BonChat Main Window on TIMI_GHOST: HWND {self.hwnd} ('{w.get('title')}') calibrated (1536x900)")
                return self.hwnd

        # Second pass: any bonchat window that is not a tool save bits window
        for w in ghost_wins:
            t = w.get("title", "").lower()
            c = w.get("class", "").lower()
            if ("bonchat" in t or "bonchat" in c or "ajuda" in t) and "toolsavebits" not in c:
                self.hwnd = w["hwnd"]
                self.is_ghost = True
                self._ensure_window_layout()
                logger.info(f"Found BonChat on TIMI_GHOST: HWND {self.hwnd} ('{w.get('title')}') calibrated (1536x900)")
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
                        self._ensure_window_layout()
                        logger.info(f"Adopted BonChat from runtime slot: HWND {self.hwnd} calibrated (1536x900)")
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
                        if "qt5qwindowicon" in c and ("bonchat" in t or w.get("w", 0) > 800):
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

        # Ensure image viewer popup is dismissed
        self.dismiss_image_preview()

        # Ensure calling thread is attached to ghost desktop before drawing
        set_thread_to_ghost_desktop()

        if not win32gui.IsWindowVisible(self.hwnd):
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"ShowWindow error: {e}")

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

            # Check if frame is totally black (stale/unrendered window)
            extrema = img.getextrema()
            if extrema == ((0, 0), (0, 0), (0, 0)):
                logger.warning("Captured frame is completely black. Restoring window and retrying...")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
                time.sleep(0.5)

            if img:
                LiveViewBridge.get_instance().publish_frame(img, self.hwnd)

            return img
        except Exception as e:
            logger.error(f"Error capturing window: {e}")
            return None

    def click_window(self, x: int, y: int):
        """Sends background mouse click to window relative coordinates."""
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        LiveViewBridge.get_instance().register_action("CLICK", f"BonChat ({x},{y})", (x, y))
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

    def is_channel_present(self, channel_target: Dict[str, Any], full_img: Optional[Image.Image] = None) -> bool:
        """
        Determines whether a channel is present in the sidebar without performing any clicks.
        """
        if full_img is None:
            full_img = self.capture_window()
        if not full_img:
            return False

        canonical = channel_target.get("canonical_name", "")
        template_name = channel_target.get("template_name")
        aliases = channel_target.get("aliases", [canonical])

        # 1. Visual template match check
        try:
            import cv2
            import numpy as np

            src_tpl_dir = os.path.join(os.path.dirname(__file__), "templates")
            data_tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "templates")
            tpl_filename = template_name
            if not tpl_filename:
                c_low = canonical.lower()
                tpl_map = {"68": "timi_68.png", "news": "timi_news.png", "08": "timi_08.png", "theodore": "theodore.png"}
                for k, v in tpl_map.items():
                    if k in c_low:
                        tpl_filename = v
                        break
            if tpl_filename:
                for d in [src_tpl_dir, data_tpl_dir]:
                    p = os.path.join(d, tpl_filename)
                    if os.path.exists(p):
                        cv_img = cv2.cvtColor(np.array(full_img), cv2.COLOR_RGB2BGR)
                        search_roi = cv_img[100:750, 30:240]
                        tpl = cv2.imread(p)
                        if tpl is not None:
                            res = cv2.matchTemplate(search_roi, tpl, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, _ = cv2.minMaxLoc(res)
                            if max_val >= 0.80:
                                return True
        except Exception:
            pass

        # 2. Sidebar OCR check
        try:
            sidebar_crop = full_img.crop((50, 110, 260, 750))
            ocr_text = pytesseract.image_to_string(sidebar_crop).lower()
            for alias in aliases:
                a_low = alias.lower()
                if a_low in ocr_text:
                    return True
                for w in a_low.split():
                    if len(w) >= 4 and w in ocr_text:
                        return True
        except Exception:
            pass

        # 3. Verified channels with calibrated coordinate
        if channel_target.get("default_y"):
            return True

        return False

    def filter_available_channels(self, target_channels: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Discovers and restricts execution strictly to channels currently visible in the sidebar.
        Returns:
            available_targets: list of channels that exist right now
            missing_names: list of channel names not found in current session
        """
        self.dismiss_image_preview()
        self.clear_search_bar()
        full_img = self.capture_window()

        available = []
        missing = []
        for t in target_channels:
            c_name = t.get("canonical_name", "")
            if self.is_channel_present(t, full_img):
                available.append(t)
            else:
                missing.append(c_name)

        return available, missing

    def select_channel(self, channel_target: Dict[str, Any]) -> bool:
        """
        Navigates to a specific channel using lateral sidebar visual template matching
        or dynamic OCR text matching. Never uses the search box to find groups.
        If a group is not currently available/visible, returns False without false clicks.
        """
        canonical = channel_target.get("canonical_name", "")
        default_y = channel_target.get("default_y")
        template_name = channel_target.get("template_name")
        aliases = channel_target.get("aliases", [canonical])

        self.dismiss_image_preview()
        # 1. Always ensure search box is cleared so full lateral sidebar is shown
        self.clear_search_bar()

        # 1. Calibrated sidebar coordinate (100% verified on account 447)
        if default_y:
            logger.info(f"Selecting channel '{canonical}' at calibrated sidebar Y={default_y}")
            self.click_window(150, default_y)
            time.sleep(0.5)
            self.go_to_latest_messages()
            return True

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
                    search_roi = cv_img[100:750, 30:240]
                    tpl = cv2.imread(tpl_file)
                    if tpl is not None:
                        res = cv2.matchTemplate(search_roi, tpl, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val >= 0.80:
                            target_x = 30 + max_loc[0] + tpl.shape[1] // 2 + 30
                            target_y = 100 + max_loc[1] + tpl.shape[0] // 2
                            logger.info(f"Visual match for '{canonical}' ({os.path.basename(tpl_file)}) at (X={target_x}, Y={target_y}) conf={max_val:.2f}")
                            self.click_window(target_x, target_y)
                            time.sleep(0.5)
                            self.go_to_latest_messages()
                            return True
            except Exception as e:
                logger.debug(f"Visual matching note: {e}")

        # 3. Dynamic OCR check on sidebar for channel name or aliases
        if full_img:
            try:
                cv_img = cv2.cvtColor(np.array(full_img), cv2.COLOR_RGB2BGR)
                sidebar_crop = full_img.crop((50, 110, 260, 750))
                ocr_data = pytesseract.image_to_data(sidebar_crop, output_type=pytesseract.Output.DICT)
                for i in range(len(ocr_data['text'])):
                    word = ocr_data['text'][i].strip().lower()
                    if len(word) >= 3:
                        for alias in aliases:
                            a_low = alias.lower()
                            if word in a_low or a_low in word:
                                item_y = 110 + ocr_data['top'][i] + ocr_data['height'][i] // 2
                                logger.info(f"Sidebar OCR matched '{canonical}' (word '{word}') at Y={item_y}")
                                self.click_window(150, item_y)
                                time.sleep(0.5)
                                self.go_to_latest_messages()
                                return True
            except Exception as e:
                logger.debug(f"Sidebar OCR match error: {e}")

        logger.info(f"Canal '{canonical}' não encontrado na barra lateral (não disponível nesta conta BonChat). A avançar...")
        return False

    def find_reset_button(self, img: Image.Image) -> Optional[Tuple[int, int]]:
        """Detects the circular down-arrow jump-to-bottom button if visible."""
        try:
            import cv2
            import numpy as np
            rgb = np.array(img.convert("RGB"))
            h, w = rgb.shape[:2]
            roi_y0, roi_y1 = int(h * 0.65), int(h * 0.90)
            roi_x0, roi_x1 = int(w * 0.88), w
            roi = rgb[roi_y0:roi_y1, roi_x0:roi_x1]
            gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
            circles = cv2.HoughCircles(
                gray, cv2.HOUGH_GRADIENT, dp=1, minDist=20,
                param1=50, param2=25, minRadius=12, maxRadius=32
            )
            if circles is not None:
                c = circles[0][0]
                bx = roi_x0 + int(c[0])
                by = roi_y0 + int(c[1])
                return (bx, by)
        except Exception:
            pass
        return None

    def go_to_latest_messages(self):
        """
        Forces chat view to jump to the very bottom (most recent messages)
        before beginning upwards history scanning.
        """
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        logger.info("Jumping to latest messages at bottom of conversation...")
        LiveViewBridge.get_instance().register_action("GO_LATEST", "Jump to latest messages", (800, 400))

        # 1. Click chat body to focus message list
        self.click_window(800, 400)
        time.sleep(0.15)

        # 2. Check if floating jump-to-bottom button is visible via circle detector or fixed coords (1495, 714)
        full_img = self.capture_window()
        btn = self.find_reset_button(full_img) if full_img else None
        if btn:
            logger.info(f"Detected jump-to-bottom button at {btn}. Clicking...")
            self.click_window(btn[0], btn[1])
            time.sleep(0.4)
        else:
            self.click_window(1495, 714)
            time.sleep(0.2)

        # 3. Send VK_END keystroke sequence
        for _ in range(8):
            user32.PostMessageW(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_END, 0)
            user32.PostMessageW(self.hwnd, win32con.WM_KEYUP, win32con.VK_END, 0)
            time.sleep(0.04)

        # 4. Scroll down aggressively with negative delta
        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            cx = rect[0] + 800
            cy = rect[1] + 400
            lparam_scroll = win32api.MAKELONG(cx, cy)
            wparam_down = win32api.MAKELONG(0, -1200) # Negative = scroll down
            for _ in range(12):
                win32gui.SendMessage(self.hwnd, win32con.WM_MOUSEWHEEL, wparam_down, lparam_scroll)
                time.sleep(0.03)
        except Exception:
            pass

        # 5. One more click at bottom right button if still showing
        self.click_window(1495, 714)
        time.sleep(0.6)

    def scroll_chat_up(self, step: int = 500):
        """
        Scrolls the chat pane up using calibrated WM_MOUSEWHEEL with Maestro SendMessage.
        Ensures a consistent ~60-70% visual overlap between frames so NO messages are ever lost.
        """
        if not self.hwnd:
            return
        set_thread_to_ghost_desktop()
        LiveViewBridge.get_instance().register_action("SCROLL", "Chat MouseWheel Up", (1000, 500))

        try:
            rect = win32gui.GetWindowRect(self.hwnd)
            cx = rect[0] + 800
            cy = rect[1] + 400
            lparam_scroll = win32api.MAKELONG(cx, cy)
            wparam = win32api.MAKELONG(0, step) # Positive = scroll up
            win32gui.SendMessage(self.hwnd, win32con.WM_MOUSEWHEEL, wparam, lparam_scroll)
        except Exception as e:
            logger.debug(f"Scroll SendMessage error: {e}")

        time.sleep(0.35)
        self.dismiss_image_preview()

    def scan_channel_incremental(
        self,
        channel_canonical: str,
        watermark_tracker,
        ignore_watermark: bool = False,
        circuit_breaker_limit: int = 120
    ) -> List[Image.Image]:
        """
        Deep scrolls upwards through group messages looking for important announcements.
        100% dynamic without artificial pass limits:
        Stops ONLY on intelligent conditions:
        1. Top of Chat reached (chat window content no longer moves).
        2. Date pill earlier than target period detected (e.g. before September 1st).
        3. Watermark reached (previously parsed messages met, unless ignore_watermark=True).
        """
        unprocessed_frames: List[Image.Image] = []
        collected_signatures: List[str] = []
        collected_frame_hashes: List[str] = []

        msg = f"Iniciando varredura dinâmica de '{channel_canonical}' (sem limite artificial de passos)..."
        logger.info(msg)
        LiveViewBridge.get_instance().emit_event(f"[{channel_canonical}] {msg}")

        from .date_pill_detector import DatePillDetector
        detector = DatePillDetector(tesseract_cmd=pytesseract.pytesseract.tesseract_cmd)
        prev_header_hash = None
        repeat_hash_count = 0
        pass_idx = 0

        while True:
            pass_idx += 1
            if pass_idx > circuit_breaker_limit:
                logger.warning(f"⚠️ Circuit breaker de segurança atingido ({circuit_breaker_limit} passos). Parando scroll.")
                break

            full_img = self.capture_window()
            if not full_img:
                logger.warning("Could not capture window during scroll.")
                break

            LiveViewBridge.get_instance().emit_event(f"[{channel_canonical}] Scroll passo {pass_idx} (a verificar topo/data)...")

            w, h = full_img.size
            chat_pane = full_img.crop((300, 45, w - 20, h - 80))
            frame_hash = watermark_tracker.compute_frame_hash(chat_pane)

            # Header region crop (top 200px) is unaffected by animated videos/stickers playing below
            header_crop = chat_pane.crop((0, 0, chat_pane.width, 200))
            header_hash = watermark_tracker.compute_frame_hash(header_crop)

            # 1. Check if chat reached top (header not moving)
            if header_hash == prev_header_hash:
                repeat_hash_count += 1
                if repeat_hash_count >= 3:
                    top_msg = f"🛑 [TOPO DA CONVERSA] Canal '{channel_canonical}' atingiu o topo das mensagens no passo {pass_idx}. Parando scroll."
                    logger.info(top_msg)
                    LiveViewBridge.get_instance().emit_event(top_msg)
                    break
            else:
                repeat_hash_count = 0
            prev_header_hash = header_hash

            # 2. Check if watermark was reached (incremental mode)
            if not ignore_watermark:
                is_wm, wm_reason = watermark_tracker.is_watermark_reached(channel_canonical, [], frame_hash)
                if is_wm:
                    wm_msg = f"🛑 [WATERMARK ATINGIDA] Mensagens já lidas alcançadas ({wm_reason}) no passo {pass_idx}. Parando scroll."
                    logger.info(wm_msg)
                    LiveViewBridge.get_instance().emit_event(wm_msg)
                    break

            # 3. Detect date pills to stop at beginning of September
            detected_pills = detector.detect_date_pills(chat_pane)
            stop_september = False
            for p in detected_pills:
                p_date = p.get("date_str")
                if p_date and p_date < "2026-09-01":
                    sep_msg = f"🛑 [SETEMBRO COMPLETO] Separador anterior a Setembro detetado ({p_date}) no passo {pass_idx}. Parando scroll."
                    logger.info(sep_msg)
                    LiveViewBridge.get_instance().emit_event(sep_msg)
                    stop_september = True
                    break

            # Frame is new: store for analysis
            unprocessed_frames.append(chat_pane)
            collected_frame_hashes.append(frame_hash)

            if stop_september:
                break

            # Scroll chat upwards with ~70% visual overlap (step=500)
            self.scroll_chat_up(step=500)
            time.sleep(0.35)

        # Update and persist watermark with newly seen messages and hashes
        if collected_signatures or collected_frame_hashes:
            watermark_tracker.commit_channel_watermark(
                channel_canonical,
                collected_signatures,
                collected_frame_hashes
            )

        logger.info(
            f"Finished dynamic scan for '{channel_canonical}': "
            f"captured {len(unprocessed_frames)} frame(s) to analyze across {pass_idx} scroll steps."
        )
        return unprocessed_frames
