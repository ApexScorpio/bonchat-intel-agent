import os
import sys
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.watermark_tracker import WatermarkTracker

def test_watermark_flow():
    test_file = BASE_DIR / "data" / "test_watermarks.json"
    if test_file.exists():
        test_file.unlink()

    tracker = WatermarkTracker(watermark_path=test_file)
    channel = "TIMI--NO.08"

    # Initially empty
    reached, reason = tracker.is_watermark_reached(channel, ["theodore_12:28"], "fakehash123")
    assert not reached, "Should not be reached on empty tracker"

    # Commit watermark
    tracker.commit_channel_watermark(
        channel,
        new_signatures=["theodore_12:28", "jonathan_20:00"],
        new_frame_hashes=["hash_abc", "hash_def"]
    )

    # Next scan: encounters theodore_12:28
    reached, reason = tracker.is_watermark_reached(channel, ["theodore_12:28", "novamensagem_14:00"], "newhash")
    assert reached, "Should detect watermark reached via signature"
    print(f"PASS: Correctly detected watermark via: {reason}")

    # Next scan: encounters frame hash
    reached, reason = tracker.is_watermark_reached(channel, ["outro_10:00"], "hash_abc")
    assert reached, "Should detect watermark reached via frame hash"
    print(f"PASS: Correctly detected watermark via: {reason}")

    # Clean up
    if test_file.exists():
        test_file.unlink()
    print("ALL WATERMARK TESTS PASSED!")

if __name__ == "__main__":
    test_watermark_flow()
