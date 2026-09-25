import time
import datetime
import logging
from .process_guard import is_maestro_running

logger = logging.getLogger("Scheduler")

SCHEDULE_TIMES = ["13:30", "21:30"]

def start_scheduler():
    from .main import run_agent
    logger.info("=== BonChat Intelligence Scheduler Active ===")
    logger.info(f"Scheduled briefing runs every day at: {SCHEDULE_TIMES}")
    
    last_run_date = {}
    pending_shift = None

    while True:
        now = datetime.datetime.now()
        current_time_str = now.strftime("%H:%M")
        current_date_str = now.strftime("%Y-%m-%d")

        # 1. Check if a scheduled slot triggered
        for sched in SCHEDULE_TIMES:
            key = f"{current_date_str}_{sched}"
            if current_time_str == sched and key not in last_run_date:
                shift_name = "TURNO MANHÃ (13:30)" if "13" in sched else "TURNO NOITE / FIM DO DIA (21:30)"
                pending_shift = (key, shift_name)
                break

        # 2. Process pending run with Maestro collision guard
        if pending_shift:
            key, shift_name = pending_shift
            maestro_active, reason = is_maestro_running()

            if maestro_active:
                logger.warning(
                    f"⚠️ [SCHEDULER GUARD] Maestro da TIMI está ativo ({reason}). "
                    f"Adiado o scan do {shift_name} para evitar sobreposição. Tentando novamente em 60s..."
                )
                time.sleep(60)
                continue
            else:
                logger.info(f"✅ Maestro livre. Iniciando scan agendado para {shift_name}...")
                try:
                    run_agent(shift_label=shift_name)
                    last_run_date[key] = True
                    pending_shift = None
                except Exception as e:
                    logger.error(f"Erro durante execução agendada: {e}")
                    pending_shift = None

        time.sleep(30)
