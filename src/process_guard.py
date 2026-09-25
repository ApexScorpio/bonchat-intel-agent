import os
import sys
import psutil
import logging
from typing import Tuple, Optional, List

logger = logging.getLogger("ProcessGuard")

MAESTRO_LOCK_FILE = r"C:\Users\lopes\.gemini\antigravity-ide\scratch\TIMI-ativador-repo\MAESTRO_TIMI.lock"

# Signatures of Maestro and its worker scripts that interact with BonChat or TIMI
TIMI_ACTIVE_SIGNATURES = [
    "maestro_timi.py",
    "maestro.py",
    "codigo timi - bonchat.py",
    "timi - ciclo fechado",
    "timi_monitor.py"
]

def is_maestro_running() -> Tuple[bool, Optional[str]]:
    """
    Checks if Maestro or any TIMI activator worker process is currently running.
    Returns (True, description) if any active process is detected, (False, None) otherwise.
    """
    # 1. Check lock file
    if os.path.exists(MAESTRO_LOCK_FILE):
        try:
            with open(MAESTRO_LOCK_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    pid = int(content)
                    if psutil.pid_exists(pid):
                        try:
                            proc = psutil.Process(pid)
                            if proc.is_running() and "python" in proc.name().lower():
                                return True, f"Lock file ativo: Maestro em execução (PID: {pid})"
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
        except Exception as e:
            logger.debug(f"Lock file check exception: {e}")

    # 2. Comprehensive process scan across system
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if not cmdline:
                    continue

                cmd_str = " ".join(cmdline).lower()

                # Check if process is running a known TIMI/Maestro script
                for sig in TIMI_ACTIVE_SIGNATURES:
                    if sig in cmd_str:
                        pid = proc.info['pid']
                        return True, f"Processo detetado: '{sig}' (PID: {pid})"

                # Check if python is running inside TIMI-ativador-repo executing an activator
                if "timi-ativador-repo" in cmd_str and ("maestro" in cmd_str or "codigo timi" in cmd_str):
                    pid = proc.info['pid']
                    return True, f"Script TIMI detetado em execução (PID: {pid})"

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        logger.error(f"Error checking processes for Maestro: {e}")

    return False, None
