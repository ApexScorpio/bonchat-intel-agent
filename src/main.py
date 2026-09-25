import os
import sys
import time
import json
import argparse
import datetime
import logging
from pathlib import Path

# Ensure package root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.config import load_config
from src.bonchat_reader import BonChatReader
from src.ai_intelligence import AIIntelligence
from src.telegram_bot import TelegramNotifier

def setup_logging():
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"intel_agent_{today}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def run_agent(shift_label: str = "MANUAL", dry_run: bool = False, specific_channel: str = None) -> bool:
    logger = logging.getLogger("MainOrchestrator")
    logger.info(f"=== Starting BonChat Intelligence Run: Shift={shift_label} ===")

    cfg = load_config()
    
    # 1. Setup reader
    reader = BonChatReader(tesseract_cmd=cfg.get("tesseract_cmd"))
    hwnd = reader.find_bonchat_window()
    if not hwnd:
        logger.error("Could not find BonChat window. Ensure BonChat is running.")
        return False

    # 2. Channels to scan
    channels = cfg.get("channels_to_monitor", [])
    if specific_channel:
        channels = [specific_channel]

    logger.info(f"Target channels ({len(channels)}): {channels}")

    # 3. Read channels
    extracted_data = {}
    for ch in channels:
        logger.info(f"Processing channel: '{ch}'...")
        coords = reader.find_group_in_sidebar(ch)
        if coords:
            reader.click_window(coords[0], coords[1])
            time.sleep(1.0)
            
            # Read chat pane
            chat_text = reader.read_active_chat(scroll_passes=3)
            logger.info(f"Channel '{ch}' read {len(chat_text)} characters.")
            extracted_data[ch] = chat_text
        else:
            logger.warning(f"Could not locate channel '{ch}' in sidebar.")
            # Still record entry so AI knows it was checked
            extracted_data[ch] = ""

    # 4. Save raw dump to data/
    today_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    data_dir = BASE_DIR / "data" / "raw_captures"
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_file = data_dir / f"capture_{today_str}.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)

    # 5. AI Summarization & Noise Filtering
    ai = AIIntelligence(
        gemini_keys=cfg.get("gemini_keys", []),
        groq_key=cfg.get("groq_key")
    )
    
    summary = ai.summarize_channels(extracted_data, shift_label=shift_label)
    logger.info("AI Briefing generated successfully.")

    # Save summary locally
    digest_dir = BASE_DIR / "data" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_file = digest_dir / f"digest_{today_str}.md"
    digest_file.write_text(summary, encoding="utf-8")
    logger.info(f"Saved digest to {digest_file}")

    # 6. Send to Telegram
    if dry_run:
        logger.info("[DRY RUN] Skipping Telegram dispatch. Summary:")
        print("\n" + "="*50)
        print(summary)
        print("="*50 + "\n")
        return True

    telegram = TelegramNotifier(
        bot_token=cfg.get("telegram_bot_token", ""),
        chat_id=cfg.get("telegram_chat_id", "")
    )
    
    ok = telegram.send_message(summary)
    logger.info(f"Run completed. Telegram status: {ok}")
    return ok

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="BonChat Intelligence & Daily Briefing Agent")
    parser.add_argument("--now", action="store_true", help="Run briefing immediately")
    parser.add_argument("--shift", type=str, default="MANUAL", help="Shift label (e.g. 13:30, 21:30, MORNING, NIGHT)")
    parser.add_argument("--channel", type=str, default=None, help="Scan a single specific channel")
    parser.add_argument("--dry-run", action="store_true", help="Do not send Telegram notification, print to console only")
    parser.add_argument("--schedule", action="store_true", help="Start background scheduler service")

    args = parser.parse_args()

    if args.schedule:
        from src.scheduler import start_scheduler
        start_scheduler()
    else:
        run_agent(shift_label=args.shift, dry_run=args.dry_run, specific_channel=args.channel)

if __name__ == "__main__":
    main()
