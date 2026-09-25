import os
import json
import re
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple
from PIL import Image

logger = logging.getLogger("WatermarkTracker")

BASE_DIR = Path(__file__).resolve().parent.parent
WATERMARK_FILE = BASE_DIR / "data" / "watermarks.json"

GENERIC_GREETINGS = {
    "bom dia", "bom diaa", "bom diaaa", "bkm dia", "bom dia maltinha",
    "boa tarde", "boa tarde pessoal", "boa tarde agentes",
    "boa noite", "ola", "olá", "ola miguel", "olaa",
    "obrigado", "obrigada", "top", "sim", "nao", "não",
    "ok", "está bem", "esta bem", "boa sorte", "parabens", "parabéns"
}

class WatermarkTracker:
    def __init__(self, watermark_path: Optional[Path] = None):
        self.watermark_path = watermark_path or WATERMARK_FILE
        self.watermarks: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.watermark_path.exists():
            try:
                with open(self.watermark_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {self.watermark_path}: {e}")
        return {}

    def save(self):
        self.watermark_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.watermark_path, "w", encoding="utf-8") as f:
            json.dump(self.watermarks, f, ensure_ascii=False, indent=2)

    @staticmethod
    def compute_frame_hash(img: Image.Image) -> str:
        """Computes a perceptual hash of a chat frame for visual comparison."""
        small = img.convert("L").resize((64, 64))
        return hashlib.sha256(small.tobytes()).hexdigest()

    @staticmethod
    def is_generic_text(text: str) -> bool:
        """Checks if a snippet is merely a trivial greeting/casual chatter."""
        clean = re.sub(r'[^a-zA-ZÀ-ÿ0-9 ]', '', text.lower()).strip()
        if not clean or len(clean) < 4:
            return True
        if clean in GENERIC_GREETINGS:
            return True
        for g in GENERIC_GREETINGS:
            if clean == g or clean.startswith(f"{g} ") or clean.endswith(f" {g}"):
                if len(clean) - len(g) < 6:
                    return True
        return False

    @staticmethod
    def parse_chat_messages(ocr_text: str) -> List[Dict[str, str]]:
        """
        Parses visible messages in a frame into structured items:
        [{ 'sender': 'antonio', 'text': 'ABCDE', 'time': '14:20', 'is_generic': False }]
        """
        messages = []
        if not ocr_text:
            return messages

        lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
        current_sender = ""
        current_time = ""
        current_body = []

        for line in lines:
            # Check for sender + time pattern e.g. "Adalberto 10:03" or "Theodore 12:28"
            match = re.search(r'^([A-Za-zÀ-ÿ0-9\.\-\_ ]{3,25})\s*[:\s]\s*(\d{1,2}:\d{2})$', line)
            if not match:
                # Also check header line with time at end
                match = re.search(r'([A-Za-zÀ-ÿ0-9\.\-\_ ]{3,25})\s+(\d{1,2}:\d{2})', line)

            if match:
                # Flush previous message if any
                if current_sender and current_body:
                    body_str = " ".join(current_body)
                    messages.append({
                        "sender": current_sender,
                        "text": body_str,
                        "time": current_time,
                        "is_generic": WatermarkTracker.is_generic_text(body_str)
                    })
                current_sender = re.sub(r'[^a-zA-ZÀ-ÿ0-9]', '', match.group(1)).lower()
                current_time = match.group(2)
                current_body = []
            else:
                if current_sender:
                    current_body.append(line)

        # Flush final message
        if current_sender and current_body:
            body_str = " ".join(current_body)
            messages.append({
                "sender": current_sender,
                "text": body_str,
                "time": current_time,
                "is_generic": WatermarkTracker.is_generic_text(body_str)
            })

        return messages

    def is_watermark_reached(
        self,
        channel_canonical: str,
        visible_messages: List[Dict[str, str]],
        frame_hash: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Determines whether we hit the boundary of the previous scan.
        Applies strict anti-false-positive rules:
        - NEVER stops on a single generic greeting (e.g. Antonio saying 'Bom dia').
        - STOPS if a distinctive non-generic message (e.g. Antonio saying 'ABCDE') matches.
        - STOPS if a multi-message chain (2+ consecutive messages) matches the previous boundary.
        - STOPS if the exact visual frame hash matches.
        """
        ch_data = self.watermarks.get(channel_canonical)
        if not ch_data:
            return False, None

        anchor_chain = ch_data.get("anchor_chain", [])
        known_hashes = set(ch_data.get("known_frame_hashes", []))

        # 1. Direct visual frame hash match
        if frame_hash in known_hashes:
            return True, f"frame_hash_match:{frame_hash[:8]}"

        if not anchor_chain or not visible_messages:
            return False, None

        # Build quick lookups for visible messages
        # 2. Check Strong Single Match (non-generic distinctive message)
        for anchor in anchor_chain:
            if anchor.get("is_generic", False):
                continue  # Never stop solely on generic greeting!

            a_sender = anchor.get("sender", "").lower()
            a_text = anchor.get("text", "").lower().strip()
            a_time = anchor.get("time", "")

            for vm in visible_messages:
                v_sender = vm.get("sender", "").lower()
                v_text = vm.get("text", "").lower().strip()
                v_time = vm.get("time", "")

                # Must match sender AND distinctive content snippet
                if a_sender and (a_sender in v_sender or v_sender in a_sender):
                    # Check text overlap or time
                    if (len(a_text) >= 5 and (a_text in v_text or v_text in a_text)) or (a_time and a_time == v_time and not vm.get("is_generic")):
                        reason = f"distinct_message:[{a_sender}: '{a_text[:20]}']"
                        logger.info(f"Watermark verified: {reason}")
                        return True, reason

        # 3. Check Multi-Message Chain Match (sequence of 2+ messages matching, even if one is casual)
        if len(anchor_chain) >= 2 and len(visible_messages) >= 2:
            matched_count = 0
            matched_senders = []

            for anchor in anchor_chain:
                a_sender = anchor.get("sender", "").lower()
                a_time = anchor.get("time", "")
                for vm in visible_messages:
                    v_sender = vm.get("sender", "").lower()
                    v_time = vm.get("time", "")
                    if a_sender in v_sender and (not a_time or not v_time or a_time == v_time):
                        matched_count += 1
                        matched_senders.append(a_sender)
                        break

            # If at least 2 distinct anchor messages are present together in this frame
            if matched_count >= 2:
                reason = f"chain_sequence_match:{matched_senders[:2]}"
                logger.info(f"Watermark verified: {reason}")
                return True, reason

        return False, None

    def commit_channel_watermark(
        self,
        channel_canonical: str,
        new_messages: List[Dict[str, str]],
        new_frame_hashes: List[str]
    ):
        """
        Commits the newest messages as the anchor chain for the next scan.
        Filters out pure greeting noise from being the sole anchor whenever possible.
        """
        import datetime
        ch_data = self.watermarks.get(channel_canonical, {})
        ch_data["last_scan_utc"] = datetime.datetime.utcnow().isoformat()

        if new_messages:
            # Pick up to 5 distinct recent messages, prioritizing non-generic ones
            distinct_recent = []
            seen = set()
            for m in reversed(new_messages):
                key = (m.get("sender"), m.get("text")[:20], m.get("time"))
                if key not in seen:
                    seen.add(key)
                    distinct_recent.append(m)
                if len(distinct_recent) >= 5:
                    break
            
            # Store in chronological order
            distinct_recent.reverse()
            ch_data["anchor_chain"] = distinct_recent

        existing_hashes = ch_data.get("known_frame_hashes", [])
        combined_hashes = list(dict.fromkeys(new_frame_hashes + existing_hashes))
        ch_data["known_frame_hashes"] = combined_hashes[:50]

        self.watermarks[channel_canonical] = ch_data
        self.save()
        logger.info(f"Committed anchor chain for '{channel_canonical}' ({len(ch_data.get('anchor_chain', []))} messages).")
