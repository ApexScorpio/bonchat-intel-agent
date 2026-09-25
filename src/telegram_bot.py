import logging
import requests
from typing import Optional

logger = logging.getLogger("TelegramBot")

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Sends message to Telegram with automatic chunking for long messages.
        """
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram bot token or chat ID is missing.")
            return False

        # Telegram limit is 4096 characters
        chunk_size = 4000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        
        all_ok = True
        for chunk in chunks:
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            try:
                resp = requests.post(self.api_url, json=payload, timeout=20)
                if resp.status_code == 200:
                    logger.info("Telegram notification sent successfully.")
                else:
                    # Fallback to plain text if markdown formatting failed
                    logger.warning(f"Telegram send failed ({resp.status_code}): {resp.text}. Retrying plain text...")
                    payload.pop("parse_mode", None)
                    retry_resp = requests.post(self.api_url, json=payload, timeout=20)
                    if retry_resp.status_code == 200:
                        logger.info("Plaintext notification sent successfully.")
                    else:
                        logger.error(f"Plaintext notification failed: {retry_resp.text}")
                        all_ok = False
            except Exception as e:
                logger.error(f"Telegram network exception: {e}")
                all_ok = False

        return all_ok
