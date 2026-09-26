import os
import re
import datetime
import logging
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np
from PIL import Image, ImageOps
import pytesseract

logger = logging.getLogger("DatePillDetector")

class DatePillDetector:
    """
    Fail-proof detector for native BonChat date separator pills (e.g., '9/17', '9/26', 'Hoje', 'Ontem').
    Strictly differentiates native UI pills from forwarded screenshots/prints based on canvas isolation.
    """

    def __init__(self, tesseract_cmd: Optional[str] = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    @staticmethod
    def normalize_date_pill(text: str, current_year: int = 2026) -> Optional[str]:
        """Normalizes extracted pill text into standard YYYY-MM-DD format."""
        t = text.strip().lower()
        now = datetime.datetime.now()

        if "hoje" in t or "today" in t:
            return now.strftime("%Y-%m-%d")
        if "ontem" in t or "yesterday" in t:
            yesterday = now - datetime.timedelta(days=1)
            return yesterday.strftime("%Y-%m-%d")

        # Match M/D or MM/DD or M-D or M.D or M\D (e.g. 9/17, 09/17, 9-17, 9.17)
        match = re.search(r'(\d{1,2})[\/\-\.\\\s](\d{1,2})', t)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{current_year:04d}-{month:02d}-{day:02d}"

        # Common OCR mistake where slash/separator is dropped: e.g. '917' -> 9/17, '926' -> 9/26
        match_num = re.search(r'^([1-9]|1[0-2])([0-3]\d)$', t)
        if match_num:
            month = int(match_num.group(1))
            day = int(match_num.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{current_year:04d}-{month:02d}-{day:02d}"

        return None

    def detect_date_pills(self, img_pil: Image.Image, chat_bounds: Optional[Tuple[int, int]] = None) -> List[Dict[str, Any]]:
        """
        Locates native UI date pills in the chat message pane.
        Returns a list of detected pills sorted vertically by Y coordinate:
        [{'y': 99, 'date_str': '2026-09-17', 'raw_text': '9/17', 'box': (x, y, w, h)}]
        """
        if img_pil is None:
            return []

        cv_img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        h, w, _ = cv_img.shape

        if chat_bounds is None:
            chat_left, chat_right = 0, w
        else:
            chat_left, chat_right = chat_bounds
            chat_left = max(0, min(chat_left, w - 100))
            chat_right = min(w, chat_right)

        center_x = (chat_left + chat_right) // 2

        # Horizontal search window around center (±120 pixels)
        strip_x1 = max(0, center_x - 120)
        strip_x2 = min(w, center_x + 120)
        strip_y1 = 30
        strip_y2 = max(strip_y1 + 50, h - 50)

        strip = cv_img[strip_y1:strip_y2, strip_x1:strip_x2]

        # BonChat native date pill color is light grey: RGB ~ 226..248
        lower_grey = np.array([226, 226, 226], dtype=np.uint8)
        upper_grey = np.array([248, 248, 248], dtype=np.uint8)
        mask = cv2.inRange(strip, lower_grey, upper_grey)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found_pills = []

        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            # Native pill size constraints: height 14..36px, width 28..150px
            if 14 <= ch <= 36 and 28 <= cw <= 150:
                global_y = strip_y1 + y
                global_x = strip_x1 + x

                # --- FAIL-PROOF ANTI-PRINTSCREEN / FORWARDED IMAGE VALIDATION ---
                # A native date pill sits isolated on the solid light chat canvas.
                # Forwarded screenshots have photos, charts, borders, or text around them.
                probe_left_x = max(0, global_x - 40)
                probe_right_x = min(w - 1, global_x + cw + 40)
                probe_y = min(h - 1, global_y + ch // 2)

                left_bg = cv_img[probe_y, probe_left_x]
                right_bg = cv_img[probe_y, probe_right_x]

                # Both left and right sides must be pure chat background canvas (>= 246 in all channels)
                is_isolated_canvas = np.all(left_bg >= 246) and np.all(right_bg >= 246)
                if not is_isolated_canvas:
                    # Candidate is inside a screenshot, photo, card, or message bubble
                    continue

                # Top or bottom must also have canvas background
                probe_top_y = max(0, global_y - 12)
                probe_bot_y = min(h - 1, global_y + ch + 12)
                probe_mid_x = min(w - 1, global_x + cw // 2)
                top_bg = cv_img[probe_top_y, probe_mid_x]
                bot_bg = cv_img[probe_bot_y, probe_mid_x]
                if not (np.all(top_bg >= 246) or np.all(bot_bg >= 246)):
                    continue

                # Crop candidate pill with 3px padding
                c_y1 = max(0, global_y - 2)
                c_y2 = min(h, global_y + ch + 2)
                c_x1 = max(0, global_x - 3)
                c_x2 = min(w, global_x + cw + 3)

                crop = cv_img[c_y1:c_y2, c_x1:c_x2]
                if crop.size == 0:
                    continue

                crop_pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                crop_large = crop_pil.resize((crop_pil.width * 3, crop_pil.height * 3), Image.Resampling.LANCZOS)
                gray = ImageOps.grayscale(crop_large)

                try:
                    txt = pytesseract.image_to_string(
                        gray,
                        config='--psm 7 -c tessedit_char_whitelist=0123456789/HojeOntem- '
                    ).strip()
                except Exception as e:
                    logger.debug(f"Pill OCR error: {e}")
                    txt = ""

                norm_date = self.normalize_date_pill(txt)
                if norm_date:
                    found_pills.append({
                        "y": global_y,
                        "date_str": norm_date,
                        "raw_text": txt,
                        "box": (global_x, global_y, cw, ch)
                    })
                    logger.info(f"Verified BonChat Date Pill: '{txt}' -> {norm_date} at Y={global_y}")

        # Sort by vertical Y (top to bottom)
        found_pills.sort(key=lambda p: p["y"])
        return found_pills
