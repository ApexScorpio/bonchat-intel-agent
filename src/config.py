import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent

def load_config() -> Dict[str, Any]:
    """
    Loads configuration looking for:
    1. config.local.json (active local credentials)
    2. config.json
    3. Fallback defaults
    """
    cfg_paths = [
        BASE_DIR / "config.local.json",
        BASE_DIR / "config.json",
        BASE_DIR / "config.example.json"
    ]
    
    for path in cfg_paths:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    logging.info(f"Loaded config from {path.name}")
                    return data
            except Exception as e:
                logging.warning(f"Failed to read {path}: {e}")
                
    return {
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "gemini_keys": [k for k in os.getenv("GEMINI_KEYS", "").split(",") if k],
        "groq_key": os.getenv("GROQ_KEY", ""),
        "tesseract_cmd": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "channels_to_monitor": [
            "timi 08",
            "timi 64",
            "grupo de agentes 20",
            "equipa de agentes de elite de timi",
            "grupo dde agentes portimao",
            "timi new",
            "Grupo de reunioes"
        ],
        "vip_senders": ["Theodore", "Johnathan", "Marcia"],
        "priority_channels": ["timi 08", "Aviso 08"],
        "schedule_times": ["13:30", "21:30"]
    }
