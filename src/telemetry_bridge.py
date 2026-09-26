import os
import sys
import time
import json
import logging
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger("TelemetryBridge")

# Target LiveView workspace directory
LIVEVIEW_WORKSPACE = r"C:\Users\lopes\.gemini\antigravity-ide\scratch\TIMI-ativador-repo"
SLOTS_DIR = os.path.join(LIVEVIEW_WORKSPACE, "_runtime", "slots")
LOGS_DIR = os.path.join(LIVEVIEW_WORKSPACE, "_runtime", "logs")
EVENTS_FILE = os.path.join(LOGS_DIR, "live_events.jsonl")
GLOBAL_DESKTOP_JPG = os.path.join(LIVEVIEW_WORKSPACE, "GHOST_DESKTOP.jpg")
LIVE_VIEW_PNG = os.path.join(LIVEVIEW_WORKSPACE, "LIVE_VIEW.png")

class LiveViewBridge:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = LiveViewBridge()
        return cls._instance

    def __init__(self):
        self.enabled = os.path.exists(LIVEVIEW_WORKSPACE)
        if self.enabled:
            try:
                os.makedirs(SLOTS_DIR, exist_ok=True)
                os.makedirs(LOGS_DIR, exist_ok=True)
            except Exception as e:
                logger.debug(f"Telemetry dir init note: {e}")
        self.action_counter = 0

    def publish_frame(self, img: Image.Image, hwnd: int = 0):
        """Pushes current BonChat window frame to LiveView so user sees real-time movement."""
        if not self.enabled or img is None:
            return
        try:
            pid = os.getpid()
            now = time.time()
            ts_ns = time.time_ns()

            # 1. Update bonchat.jpg slot atomically
            slot_file = os.path.join(SLOTS_DIR, "bonchat.jpg")
            tmp_slot = os.path.join(SLOTS_DIR, f"bonchat.tmp_{ts_ns}.jpg")
            img.save(tmp_slot, "JPEG", quality=85)
            if os.path.exists(tmp_slot):
                for _ in range(5):
                    try:
                        if os.path.exists(slot_file):
                            os.remove(slot_file)
                        os.replace(tmp_slot, slot_file)
                        break
                    except Exception:
                        time.sleep(0.01)
                if os.path.exists(tmp_slot):
                    try: os.remove(tmp_slot)
                    except: pass

            # 2. Update bonchat.json metadata for liveness check
            meta_file = os.path.join(SLOTS_DIR, "bonchat.json")
            tmp_meta = os.path.join(SLOTS_DIR, f"bonchat.tmp_{ts_ns}.json")
            meta_data = {
                "slot": "bonchat",
                "last_update": now,
                "pid": pid,
                "alive": True,
                "hwnd": hwnd,
                "size": list(img.size),
                "timestamp_str": time.strftime("%H:%M:%S")
            }
            with open(tmp_meta, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, indent=2)
            if os.path.exists(tmp_meta):
                for _ in range(5):
                    try:
                        if os.path.exists(meta_file):
                            os.remove(meta_file)
                        os.replace(tmp_meta, meta_file)
                        break
                    except Exception:
                        time.sleep(0.01)
                if os.path.exists(tmp_meta):
                    try: os.remove(tmp_meta)
                    except: pass

            # 3. Direct GHOST_DESKTOP.jpg and LIVE_VIEW.png update as fallback
            tmp_global = os.path.join(LIVEVIEW_WORKSPACE, f"GHOST_DESKTOP.tmp_{ts_ns}.jpg")
            img.save(tmp_global, "JPEG", quality=85)
            if os.path.exists(tmp_global):
                try:
                    if os.path.exists(GLOBAL_DESKTOP_JPG):
                        os.remove(GLOBAL_DESKTOP_JPG)
                    os.replace(tmp_global, GLOBAL_DESKTOP_JPG)
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"LiveView publish error: {e}")

    def register_action(self, action_type: str, target: str, coords: Tuple[int, int]):
        """Registers a user action (click/scroll) so the LiveView draws an action crosshair."""
        if not self.enabled:
            return
        try:
            self.action_counter += 1
            now = time.time()
            marker_file = os.path.join(SLOTS_DIR, "active_marker.json")
            tmp_marker = os.path.join(SLOTS_DIR, f"active_marker.tmp_{time.time_ns()}.json")
            marker_data = {
                "action_id": self.action_counter,
                "type": action_type,
                "target": target,
                "coords": coords,
                "timestamp": now,
                "expires_at": now + 2.0,
                "source": "INTEL_AGENT",
                "pid": os.getpid()
            }
            with open(tmp_marker, "w", encoding="utf-8") as f:
                json.dump(marker_data, f)
            if os.path.exists(tmp_marker):
                if os.path.exists(marker_file):
                    try: os.remove(marker_file)
                    except: pass
                os.replace(tmp_marker, marker_file)
        except Exception:
            pass

    def emit_event(self, message: str, ev_type: str = "LOG", action_id: int = 0):
        """Emits an event to live_events.jsonl for real-time dashboard log view."""
        # Also print to stdout with immediate flush for console watchers
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)
        if not self.enabled:
            return
        try:
            event_obj = {
                "timestamp": time.strftime("%H:%M:%S"),
                "source": "INTEL_AGENT",
                "pid": os.getpid(),
                "action_id": action_id or self.action_counter,
                "type": ev_type,
                "message": message
            }
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_obj, ensure_ascii=False) + "\n")
        except Exception:
            pass
