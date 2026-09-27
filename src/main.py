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
from src.telemetry_bridge import LiveViewBridge

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

def purge_transient_data(max_digest_days: int = 3):
    """Purges ALL transient/temporary files to prevent disk bloat on the local PC."""
    import shutil
    purge_logger = logging.getLogger("PurgeGuard")
    freed = 0
    try:
        # 1. In-flight frame captures (always safe to delete — all knowledge is in KB)
        captures_dir = BASE_DIR / "data" / "captures"
        if captures_dir.exists():
            sz = sum(f.stat().st_size for f in captures_dir.rglob("*") if f.is_file())
            shutil.rmtree(str(captures_dir), ignore_errors=True)
            freed += sz

        # 2. Digests older than max_digest_days (preserved on GitHub, not needed locally)
        now = time.time()
        digest_dir = BASE_DIR / "data" / "digests"
        if digest_dir.exists():
            for f in digest_dir.glob("*.md"):
                if now - f.stat().st_mtime > max_digest_days * 86400:
                    try:
                        freed += f.stat().st_size
                        f.unlink()
                    except Exception: pass

        # 3. AI hash cache entries older than 7 days (safe to rebuild)
        cache_dir = BASE_DIR / "data" / "cache"
        if cache_dir.exists():
            for f in cache_dir.iterdir():
                if f.is_file() and now - f.stat().st_mtime > 7 * 86400:
                    try:
                        freed += f.stat().st_size
                        f.unlink()
                    except Exception: pass

        if freed > 0:
            purge_logger.info(f"🧹 [PURGE] Libertados {freed / (1024**2):.1f} MB de ficheiros temporários do PC.")
    except Exception as e:
        purge_logger.debug(f"Purge note: {e}")

def sync_to_github(commit_msg: str = "chore(intel): auto-sync intelligence and digests to GitHub"):
    """Automatically synchronizes all intelligence and documents directly to GitHub."""
    try:
        import subprocess
        logger = logging.getLogger("GitSync")
        logger.info("Sincronizando base de dados de inteligência diretamente para o GitHub...")
        subprocess.run(["git", "add", "data/digests", "knowledge_base"], cwd=str(BASE_DIR), capture_output=True, check=False)
        diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(BASE_DIR))
        if diff_check.returncode != 0:
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(BASE_DIR), capture_output=True, check=False)
            push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, text=True, check=False)
            if push_res.returncode == 0:
                logger.info("Base de dados no GitHub atualizada com sucesso.")
            else:
                logger.warning(f"Git push status: {push_res.stderr.strip()}")
        else:
            logger.info("GitHub já se encontra 100% atualizado.")
    except Exception as e:
        logging.getLogger("GitSync").warning(f"Erro ao sincronizar com GitHub: {e}")

def run_agent(shift_label: str = "MANUAL", dry_run: bool = False, specific_channel: str = None, deep_extract: bool = False) -> bool:
    logger = logging.getLogger("MainOrchestrator")
    logger.info(f"=== Starting BonChat Intelligence Run: Shift={shift_label}, DeepExtract={deep_extract} ===")

    # Keep local PC clean: purge transient capture files
    purge_transient_data()

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

    # 0.1 Autonomous harvest of official documents & slides
    try:
        from src.document_harvester import DocumentHarvester
        harvester = DocumentHarvester()
        harvester.run_harvest()
    except Exception as e:
        logger.warning(f"Document harvesting note: {e}")

    # 1. Setup reader & find window
    reader = BonChatReader(tesseract_cmd=cfg.get("tesseract_cmd"))
    hwnd = reader.find_bonchat_window()
    if not hwnd:
        logger.error("Could not find BonChat window. Ensure BonChat is running on TIMI_GHOST.")
        return False

    watermark_tracker = WatermarkTracker()
    if deep_extract:
        # Full deep extraction across September: bypass watermark and scroll until top or date boundary
        watermark_tracker.channel_states = {}
        logger.info("Modo de extração contínua ativo: scroll dinâmico sem limite artificial de passos.")
    else:
        logger.info("Modo incremental diário: scroll dinâmico até bater em mensagens já vistas (watermark) ou topo.")

    kb = KnowledgeBase()

    # 2. Channels to scan
    targets = cfg.get("channel_targets", [])
    if specific_channel:
        targets = [t for t in targets if specific_channel.lower() in t.get("canonical_name", "").lower()]
        if not targets:
            targets = [{"canonical_name": specific_channel, "display_name": specific_channel, "search_term": specific_channel}]
    else:
        # Autonomous discovery: restrict strictly to channels currently visible/available
        available_targets, missing_names = reader.filter_available_channels(targets)
        if available_targets:
            avail_names = [t.get("canonical_name") for t in available_targets]
            logger.info(f"🔎 [AUTONOMIA] Canais ativos e presentes no BonChat ({len(available_targets)}/{len(targets)}): {avail_names}")
            if missing_names:
                logger.info(f"ℹ️ [FILTRO] {len(missing_names)} canal(is) configurado(s) não presentes nesta conta (ignorados sem erro): {missing_names}")
            targets = available_targets

    logger.info(f"Target channels to scan ({len(targets)} channels)")

    ai = AIIntelligence(
        gemini_keys=cfg.get("gemini_keys", []),
        groq_key=cfg.get("groq_key"),
        quota_cfg=cfg.get("quota_protection")
    )

    channel_reports = {}
    today_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    total_channels = len(targets)

    # 3. Process each channel incrementally
    for idx_target, target in enumerate(targets, 1):
        c_name = target.get("canonical_name", "Canal")
        d_name = target.get("display_name", c_name)
        step_prefix = f"[PASSO {idx_target}/{total_channels}]"
        
        step_msg = f"{step_prefix} [NAVEGAÇÃO] Mudando para o canal '{c_name}'..."
        logger.info(step_msg)
        LiveViewBridge.get_instance().emit_event(step_msg)

        ok = reader.select_channel(target)
        if not ok:
            warn_msg = f"{step_prefix} [AVISO] Não foi possível selecionar o canal '{c_name}' no sidebar."
            logger.warning(warn_msg)
            LiveViewBridge.get_instance().emit_event(warn_msg)
            continue

        time.sleep(1.0)

        # Deep scroll backwards until hitting previous scan's watermark
        scroll_msg = f"{step_prefix} [SCROLL] A efetuar leitura incremental de mensagens antigas..."
        logger.info(scroll_msg)
        LiveViewBridge.get_instance().emit_event(scroll_msg)

        new_frames = reader.scan_channel_incremental(
            channel_canonical=c_name,
            watermark_tracker=watermark_tracker,
            ignore_watermark=deep_extract
        )

        if not new_frames:
            uptodate_msg = f"{step_prefix} [WATERMARK] Canal '{c_name}' 100% atualizado. 0 novas mensagens a processar."
            logger.info(uptodate_msg)
            LiveViewBridge.get_instance().emit_event(uptodate_msg)
            continue

        # In-memory AI Multimodal Vision analysis (zero disk bloat)
        ai_msg = f"{step_prefix} [IA VISION] A analisar {len(new_frames)} novos frames em memória para '{c_name}'..."
        logger.info(ai_msg)
        LiveViewBridge.get_instance().emit_event(ai_msg)

        analysis, entries = ai.analyze_channel_capture(c_name, new_frames)
        
        # Record structured intel entries into Knowledge Base
        if entries:
            for item in entries:
                kb.add_entry(
                    date_str=item.get("date_str", datetime.datetime.now().strftime("%Y-%m-%d")),
                    time_str=item.get("time_str", "N/A"),
                    channel=c_name,
                    authority=item.get("authority", "Autoridade"),
                    content_type=item.get("content_type", "Aviso"),
                    verbatim_text=item.get("verbatim_text", ""),
                    key_takeaways=item.get("key_takeaways", [])
                )
            logger.info(f"{step_prefix} [BASE DE DADOS] {len(entries)} registo(s) estruturado(s) adicionados à base de conhecimento para '{c_name}'.")

        if analysis and "sem novidades" not in analysis.lower():
            logger.info(f"{step_prefix} [ACHADOS] '{c_name}': {analysis[:80]}...")
            LiveViewBridge.get_instance().emit_event(f"{step_prefix} [INTELIGÊNCIA] Novidade detetada em '{c_name}'!")
            channel_reports[d_name] = analysis
        else:
            no_news_msg = f"{step_prefix} [STATUS] Sem comunicados críticos da autoridade em '{c_name}'."
            logger.info(no_news_msg)
            LiveViewBridge.get_instance().emit_event(no_news_msg)

        # ── PER-CHANNEL SYNC & PURGE ──────────────────────────────────────────
        # Immediately commit the new knowledge for this channel to GitHub and
        # purge all temporary in-flight frame data from the local disk so that
        # long multi-group runs never fill up S:
        sync_channel_msg = f"{step_prefix} [SYNC] A sincronizar conhecimento do canal '{c_name}' para o GitHub e a limpar temporários..."
        logger.info(sync_channel_msg)
        LiveViewBridge.get_instance().emit_event(sync_channel_msg)
        sync_to_github(commit_msg=f"chore(intel): [{c_name}] knowledge sync {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        purge_transient_data(max_digest_days=3)
        # Release frame list from memory immediately
        new_frames.clear()
        # ─────────────────────────────────────────────────────────────────────

    # 4. Generate final briefing
    full_digest = ai.generate_full_briefing(channel_reports, shift_label=shift_label)
    logger.info("Executive Briefing finalized.")

    # Save digest locally and push immediately to GitHub cloud database
    digest_dir = BASE_DIR / "data" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_file = digest_dir / f"digest_{today_str}.md"
    digest_file.write_text(full_digest, encoding="utf-8")
    logger.info(f"Digest saved to {digest_file}")

    # Auto-sync intelligence & documents to GitHub database
    sync_to_github(commit_msg=f"chore(intel): auto-sync briefing {today_str} to GitHub")

    # Purge any remaining temporary artifacts
    purge_transient_data()

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
    parser.add_argument("--deep-extract", action="store_true", help="Perform deep historical extraction of VIP messages across channels")
    parser.add_argument("--schedule", action="store_true", help="Start background scheduler service")

    args = parser.parse_args()

    if args.schedule:
        from src.scheduler import start_scheduler
        start_scheduler()
    else:
        run_agent(
            shift_label=args.shift,
            dry_run=args.dry_run,
            specific_channel=args.channel,
            deep_extract=args.deep_extract
        )

if __name__ == "__main__":
    main()
