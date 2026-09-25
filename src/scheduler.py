import time
import datetime
import logging
from .main import run_agent

logger = logging.getLogger("Scheduler")

SCHEDULE_TIMES = ["13:30", "21:30"]

def start_scheduler():
    logger.info(f"=== BonChat Intelligence Scheduler Active ===")
    logger.info(f"Scheduled briefing runs every day at: {SCHEDULE_TIMES}")
    
    last_run_date = {}

    while True:
        now = datetime.datetime.now()
        current_time_str = now.strftime("%H:%M")
        current_date_str = now.strftime("%Y-%m-%d")

        for sched in SCHEDULE_TIMES:
            key = f"{current_date_str}_{sched}"
            if current_time_str == sched and key not in last_run_date:
                shift_name = "TURNO MANHÃ (13:30)" if "13" in sched else "TURNO NOITE / FIM DO DIA (21:30)"
                logger.info(f"Triggering scheduled run for {sched} ({shift_name})...")
                
                try:
                    run_agent(shift_label=shift_name)
                    last_run_date[key] = True
                except Exception as e:
                    logger.error(f"Error during scheduled run: {e}")

        # Sleep 30 seconds between checks
        time.sleep(30)
