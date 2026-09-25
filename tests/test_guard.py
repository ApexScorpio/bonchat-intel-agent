import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.process_guard import is_maestro_running, MAESTRO_LOCK_FILE

def test_guard():
    print("Testing Maestro guard when Maestro is NOT running...")
    active, reason = is_maestro_running()
    print(f"Status: active={active}, reason={reason}")

    # Simulate active lock file with current python pid
    print("Testing lock file detection with simulated PID...")
    test_lock = MAESTRO_LOCK_FILE + ".test_simulation"
    try:
        import src.process_guard as pg
        original_lock = pg.MAESTRO_LOCK_FILE
        pg.MAESTRO_LOCK_FILE = test_lock
        with open(test_lock, "w") as f:
            f.write(str(os.getpid()))

        active_sim, reason_sim = pg.is_maestro_running()
        assert active_sim, "Should detect active lock file"
        print(f"PASS: Correctly detected simulated active process: {reason_sim}")
    finally:
        pg.MAESTRO_LOCK_FILE = original_lock
        if os.path.exists(test_lock):
            os.remove(test_lock)

    print("ALL PROCESS GUARD TESTS PASSED 100%!")

if __name__ == "__main__":
    test_guard()
