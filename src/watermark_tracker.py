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
    def extract_text_signatures(ocr_text: str) -> List[str]:
        """
        Extracts sender+timestamp or header signatures from OCR text.
        Example signatures:
        - 'Theodore_12:28'
        - 'Jonathan_20:00'
        - 'Adalberto_10:03'
        - 'Numero_sorte_678126'
        """
        signatures = []
        if not ocr_text:
            return signatures

        # Match name + time (e.g., "Theodore 12:28", "Andrei Marjineanu: 17:51")
        matches = re.findall(r'([A-Za-zÀ-ÿ0-9\.\-\_ ]{3,25})\s*[:\s]\s*(\d{1,2}:\d{2})', ocr_text)
        for name, tm in matches:
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', name).lower()
            if len(clean_name) >= 3:
                signatures.append(f"{clean_name}_{tm}")

        # Pinned messages / special markers
        if "mensagem fixada" in ocr_text.lower():
            signatures.append("marker_mensagem_fixada")
        if "aviso importante" in ocr_text.lower():
            signatures.append("marker_aviso_importante")
        if "campanha de apoio" in ocr_text.lower():
            signatures.append("marker_campanha_apoio")

        return list(set(signatures))

    def get_channel_signatures(self, channel_canonical: str) -> Set[str]:
        """Gets known signatures for a given channel."""
        data = self.watermarks.get(channel_canonical, {})
        return set(data.get("known_signatures", []))

    def is_watermark_reached(self, channel_canonical: str, frame_signatures: List[str], frame_hash: str) -> Tuple[bool, Optional[str]]:
        """
        Checks whether the currently visible chat frame contains signatures or visual hashes
        that were already processed in a previous scan.
        """
        ch_data = self.watermarks.get(channel_canonical)
        if not ch_data:
            return False, None

        known_sigs = set(ch_data.get("known_signatures", []))
        known_hashes = set(ch_data.get("known_frame_hashes", []))

        # Check visual frame hash match
        if frame_hash in known_hashes:
            return True, f"frame_hash:{frame_hash[:8]}"

        # Check text signature match
        for sig in frame_signatures:
            if sig in known_sigs:
                return True, f"signature:{sig}"

        return False, None

    def commit_channel_watermark(
        self,
        channel_canonical: str,
        new_signatures: List[str],
        new_frame_hashes: List[str],
        max_signatures: int = 150
    ):
        """
        Updates the channel watermark with new signatures and frame hashes seen in this scan,
        keeping a sliding window of the most recent entries.
        """
        ch_data = self.watermarks.get(channel_canonical, {
            "known_signatures": [],
            "known_frame_hashes": [],
            "last_scan_utc": ""
        })

        import datetime
        ch_data["last_scan_utc"] = datetime.datetime.utcnow().isoformat()

        # Merge and keep recent window
        existing_sigs = ch_data.get("known_signatures", [])
        combined_sigs = list(dict.fromkeys(new_signatures + existing_sigs))
        ch_data["known_signatures"] = combined_sigs[:max_signatures]

        existing_hashes = ch_data.get("known_frame_hashes", [])
        combined_hashes = list(dict.fromkeys(new_frame_hashes + existing_hashes))
        ch_data["known_frame_hashes"] = combined_hashes[:50]

        self.watermarks[channel_canonical] = ch_data
        self.save()
        logger.info(f"Committed watermark for '{channel_canonical}': {len(ch_data['known_signatures'])} signatures tracked.")
