import os
import sys
import time
import json
import argparse
import datetime
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.config import load_config
from src.bonchat_reader import BonChatReader
from src.ai_intelligence import AIIntelligence
from src.telegram_bot import TelegramNotifier
from src.watermark_tracker import WatermarkTracker
from src.knowledge_base import KnowledgeBase

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
    logger.info(f"=== Starting BonChat Incremental Intelligence Run: Shift={shift_label} ===")

    # 0. Maestro & Activator Collision Guard
    from src.process_guard import is_maestro_running
    maestro_active, reason = is_maestro_running()
    if maestro_active:
        logger.warning(
            f"🛑 [MAESTRO GUARD] O Maestro da TIMI está em execução ativa ({reason})! "
            f"A execução do BonChat Intel Agent foi cancelada para evitar sobreposição de scripts."
        )
        return False

    cfg = load_config()

    # 1. Setup reader & find window
    reader = BonChatReader(tesseract_cmd=cfg.get("tesseract_cmd"))
    hwnd = reader.find_bonchat_window()
    if not hwnd:
        logger.error("Could not find BonChat window. Ensure BonChat is running on TIMI_GHOST.")
        return False

    watermark_tracker = WatermarkTracker()
    kb = KnowledgeBase()

    # 2. Channels to scan
    targets = cfg.get("channel_targets", [])
    if specific_channel:
        targets = [t for t in targets if specific_channel.lower() in t.get("canonical_name", "").lower()]
        if not targets:
            targets = [{"canonical_name": specific_channel, "display_name": specific_channel, "search_term": specific_channel}]

    logger.info(f"Target channels to scan ({len(targets)} channels)")

    ai = AIIntelligence(
        gemini_keys=cfg.get("gemini_keys", []),
        groq_key=cfg.get("groq_key"),
        quota_cfg=cfg.get("quota_protection")
    )

    channel_reports = {}
    today_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    raw_crops_dir = BASE_DIR / "data" / "captures" / today_str

    max_scroll_passes = cfg.get("max_scroll_passes", 15)

    # 3. Process each channel incrementally
    for target in targets:
        c_name = target.get("canonical_name", "Canal")
        d_name = target.get("display_name", c_name)
        logger.info(f"Navigating to '{c_name}'...")

        ok = reader.select_channel(target)
        if not ok:
            logger.warning(f"Could not navigate to channel '{c_name}'.")
            continue

        time.sleep(1.0)

        # Deep scroll backwards until hitting previous scan's watermark
        new_frames = reader.scan_channel_incremental(
            channel_canonical=c_name,
            watermark_tracker=watermark_tracker,
            max_scroll_passes=max_scroll_passes
        )

        if not new_frames:
            logger.info(f"Channel '{c_name}' is already up to date with previous scan. 0 new frames to process.")
            continue

        # Save crops for auditing
        raw_crops_dir.mkdir(parents=True, exist_ok=True)
        for idx, img in enumerate(new_frames):
            clean_name = "".join(c for c in c_name if c.isalnum() or c in ('_', '-'))
            img.save(str(raw_crops_dir / f"{clean_name}_frame_{idx+1}.jpg"), format="JPEG", quality=85)

        # Analyze new frames with Gemini Multimodal Vision (with Quota Guard)
        logger.info(f"Analyzing {len(new_frames)} new frame(s) for '{c_name}' with Gemini Vision...")
        analysis = ai.analyze_channel_capture(c_name, new_frames)
        if analysis and "sem novidades" not in analysis.lower():
            logger.info(f"Findings for '{c_name}': {analysis[:80]}...")
            channel_reports[d_name] = analysis
        else:
            logger.info(f"No critical authority updates found in '{c_name}'.")

    # 4. Generate final briefing
    full_digest = ai.generate_full_briefing(channel_reports, shift_label=shift_label)
    logger.info("Executive Briefing finalized.")

    # Save digest
    digest_dir = BASE_DIR / "data" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_file = digest_dir / f"digest_{today_str}.md"
    digest_file.write_text(full_digest, encoding="utf-8")
    logger.info(f"Digest saved to {digest_file}")

    # 5. Dispatch to Telegram
    if dry_run:
        logger.info("[DRY RUN] Skipping Telegram dispatch. Briefing output:")
        print("\n" + "="*50)
        print(full_digest)
        print("="*50 + "\n")
        return True

    telegram = TelegramNotifier(
        bot_token=cfg.get("telegram_bot_token", ""),
        chat_id=cfg.get("telegram_chat_id", "")
    )
    sent = telegram.send_message(full_digest)
    logger.info(f"Telegram notification sent: {sent}")
    return sent

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="BonChat Incremental Intelligence Agent")
    parser.add_argument("--now", action="store_true", help="Run briefing immediately")
    parser.add_argument("--shift", type=str, default="MANUAL", help="Shift label (e.g. 13:30, 21:30)")
    parser.add_argument("--channel", type=str, default=None, help="Scan a single specific channel")
    parser.add_argument("--dry-run", action="store_true", help="Print briefing to console without sending to Telegram")
    parser.add_argument("--schedule", action="store_true", help="Start background scheduler service")

    args = parser.parse_args()

    if args.schedule:
        from src.scheduler import start_scheduler
        start_scheduler()
    else:
        run_agent(shift_label=args.shift, dry_run=args.dry_run, specific_channel=args.channel)

if __name__ == "__main__":
    main()
