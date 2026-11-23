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

        # 4. Any root debug captures or screenshots
        for p in BASE_DIR.glob("*.png"):
            try:
                freed += p.stat().st_size
                p.unlink()
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
        subprocess.run(["git", "add", ".gitignore", "src", "data/digests", "knowledge_base"], cwd=str(BASE_DIR), capture_output=True, check=False)
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

def _start_liveview_for_intel(logger):
    """Arranca o LiveView (daemon + bridges Ghost) antes do Intel Agent trabalhar."""
    try:
        timi_code = r"S:\Users\lopes\Documents\TIMI_FIELD_WORKSPACE\code"
        if os.path.isdir(timi_code) and timi_code not in sys.path:
            sys.path.insert(0, timi_code)
        from timi_liveview_guard import ensure_liveview_subsystem_ready
        st = ensure_liveview_subsystem_ready(auto_start=True)
        logger.info(f"🖥️ [LIVEVIEW] Pronto={st.get('ready')} | HTTP_8088={st.get('http_8088')} | BONCHAT={st.get('bonchat_bridge')}")
    except Exception as e:
        logger.warning(f"Aviso ao arrancar LiveView para Intel Agent: {e}")


def _cleanup_liveview_after_intel(logger, launched_pid=None):
    """Fecha BonChat + stack LiveView ao terminar o Intel Agent, se Maestro/Guardian não estiverem ativos."""
    try:
        import psutil
        active_other = False
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                if "python" in (p.info.get("name") or "").lower():
                    cmd = " ".join(str(c) for c in (p.info.get("cmdline") or [])).lower()
                    if any(k in cmd for k in ("maestro_timi.py", "timi_guardian.py", "codigo timi -")):
                        active_other = True
                        break
            except Exception:
                continue
        if active_other:
            logger.info("🛡️ [POUPANÇA] Maestro/Guardian ativo — a manter BonChat/LiveView ligados.")
            return
        lv_targets = (
            "liveview_direct_ghost_bridge.py",
            "liveview_browser_ghost_bridge.py",
            "timi_capture_persistent.py",
            "liveview_daemon.py",
        )
        closed = 0
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (p.info.get("name") or "").lower()
                if name == "bonchat.exe":
                    p.terminate()
                    closed += 1
                elif "python" in name:
                    cmd = " ".join(str(c) for c in (p.info.get("cmdline") or [])).lower()
                    if any(t in cmd for t in lv_targets):
                        p.terminate()
                        closed += 1
            except Exception:
                continue
        if closed:
            logger.info(f"💤 [POUPANÇA] Encerrados {closed} processo(s) BonChat/LiveView após Intel Agent.")
    except Exception as e:
        logger.debug(f"Cleanup after intel note: {e}")


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

    # 0.0 Arrancar LiveView sempre que o Intel Agent vai trabalhar
    _start_liveview_for_intel(logger)

    cfg = load_config()

    # 0.1 Autonomous harvest of official documents & slides
    try:
        from src.document_harvester import DocumentHarvester
        harvester = DocumentHarvester()
        harvester.run_harvest()
    except Exception as e:
        logger.warning(f"Document harvesting note: {e}")

    # 1. Setup reader & find window (prioridade absoluta à conta 928250447 que tem TODOS os grupos, com fallback)
    reader = BonChatReader(tesseract_cmd=cfg.get("tesseract_cmd"))
    primary_exe = cfg.get("primary_account_exe") or r"S:\Users\lopes\AppData\Roaming\BonChat_Acc3_928250447\BonChat.exe"
    hwnd = None
    launched_primary_pid = None
    if primary_exe and os.path.exists(primary_exe):
        hwnd, launched_primary_pid = reader.find_bonchat_window_for_exe(primary_exe, auto_launch=True)
        if hwnd:
            logger.info(f"🎯 [CONTA PRINCIPAL] A usar conta prioritária ({os.path.basename(os.path.dirname(primary_exe))}, HWND {hwnd}).")
        else:
            logger.warning(f"⚠️ [FALLBACK] Conta prioritária ({primary_exe}) indisponível — a tentar outra janela BonChat...")
    if not hwnd:
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

    # 2. Channels to scan (separando canais da Conta 1 vs canais de contas secundárias ex: Conta 3 Agentes)
    raw_targets = cfg.get("channel_targets", [])
    if specific_channel:
        targets = [t for t in raw_targets if specific_channel.lower() in t.get("canonical_name", "").lower()]
        if not targets:
            targets = [{"canonical_name": specific_channel, "display_name": specific_channel, "search_term": specific_channel}]
        extra_account_targets = []
    else:
        primary_targets = [t for t in raw_targets if not t.get("account_exe")]
        extra_account_targets = [t for t in raw_targets if t.get("account_exe")]
        # Autonomous discovery on Conta 1
        available_targets, missing_names = reader.filter_available_channels(primary_targets)
        if available_targets:
            avail_names = [t.get("canonical_name") for t in available_targets]
            logger.info(f"🔎 [AUTONOMIA] Canais ativos na Conta 1 ({len(available_targets)}/{len(primary_targets)}): {avail_names}")
            if missing_names:
                logger.info(f"ℹ️ [FILTRO] {len(missing_names)} canal(is) não presentes na Conta 1: {missing_names}")
            targets = available_targets
        else:
            targets = primary_targets

    targets = list(targets) + list(extra_account_targets)
    logger.info(f"Target channels to scan ({len(targets)} channels, incl. {len(extra_account_targets)} de contas secundárias)")

    ai = AIIntelligence(
        gemini_keys=cfg.get("gemini_keys", []),
        groq_key=cfg.get("groq_key"),
        quota_cfg=cfg.get("quota_protection")
    )

    channel_reports = {}
    all_discovered_entries = []
    today_str = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    total_channels = len(targets)
    primary_hwnd = reader.hwnd
    launched_extra_pids = {}

    # 3. Process each channel incrementally
    try:
        for idx_target, target in enumerate(targets, 1):
            c_name = target.get("canonical_name", "Canal")
            d_name = target.get("display_name", c_name)
            step_prefix = f"[PASSO {idx_target}/{total_channels}]"

            # Alternar janela para conta secundária (ex: Conta 3 para grupos de agentes) se configurada
            acc_exe = target.get("account_exe")
            if acc_exe:
                sec_hwnd, sec_pid = reader.find_bonchat_window_for_exe(acc_exe, auto_launch=True)
                if sec_pid:
                    launched_extra_pids[acc_exe] = sec_pid
                if not sec_hwnd:
                    logger.warning(f"{step_prefix} [AVISO] Conta secundária indisponível para '{c_name}'.")
                    continue
            else:
                reader.hwnd = primary_hwnd

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
                    item["channel"] = c_name
                    kb.add_entry(
                        date_str=item.get("date_str", datetime.datetime.now().strftime("%Y-%m-%d")),
                        time_str=item.get("time_str", "N/A"),
                        channel=c_name,
                        authority=item.get("authority", "Autoridade"),
                        content_type=item.get("content_type", "Aviso"),
                        verbatim_text=item.get("verbatim_text", ""),
                        key_takeaways=item.get("key_takeaways", [])
                    )
                all_discovered_entries.extend(entries)
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
            sync_channel_msg = f"{step_prefix} [SYNC] A sincronizar conhecimento do canal '{c_name}' para o GitHub e a limpar temporários..."
            logger.info(sync_channel_msg)
            LiveViewBridge.get_instance().emit_event(sync_channel_msg)
            sync_to_github(commit_msg=f"chore(intel): [{c_name}] knowledge sync {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
            purge_transient_data(max_digest_days=3)
            new_frames.clear()
            # ─────────────────────────────────────────────────────────────────────
    finally:
        for _exe, _pid in launched_extra_pids.items():
            reader.close_pid(_pid)
        reader.hwnd = primary_hwnd

    # 4. Agendamento Automático de Reuniões & Atividades no Windows Task Scheduler
    scheduled_tasks = []
    try:
        from src.activity_scheduler import scan_and_schedule_from_entries
        scheduled_tasks = scan_and_schedule_from_entries(all_discovered_entries)
        if scheduled_tasks:
            logger.info(f"📅 [AGENDADOR DINÂMICO] {len(scheduled_tasks)} atividade(s) agendada(s) no Windows Task Scheduler!")
            for st in scheduled_tasks:
                logger.info(f"   -> Reunião: {st['meeting_time']} | Tarefa: {st['task_name']} | Motivo: {st['reason']}")
    except Exception as e_sched:
        logger.warning(f"Aviso ao executar agendamento dinâmico: {e_sched}")

    # 5. Generate final executive briefing (limpo de código, sem repetições)
    full_digest = ai.generate_full_briefing(
        channel_reports,
        shift_label=shift_label,
        all_entries=all_discovered_entries,
        scheduled_tasks=scheduled_tasks
    )
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
        _cleanup_liveview_after_intel(logger, launched_pid=launched_primary_pid)
        return True

    telegram = TelegramNotifier(
        bot_token=cfg.get("telegram_bot_token", ""),
        chat_id=cfg.get("telegram_chat_id", "")
    )
    sent = telegram.send_message(full_digest)
    logger.info(f"Telegram notification sent: {sent}")
    _cleanup_liveview_after_intel(logger, launched_pid=launched_primary_pid)
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
