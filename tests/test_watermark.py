import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.watermark_tracker import WatermarkTracker

def test_watermark_anti_false_positive():
    test_file = BASE_DIR / "data" / "test_watermarks.json"
    if test_file.exists():
        test_file.unlink()

    tracker = WatermarkTracker(watermark_path=test_file)
    channel = "TIMI--NO.08"

    # Previous scan ended with António saying distinctive content "ABCDE" at 14:20
    # and previous message was Bruno saying "Bom dia"
    prev_scan_messages = [
        {"sender": "bruno", "text": "Bom dia", "time": "14:15", "is_generic": True},
        {"sender": "antonio", "text": "ABCDE", "time": "14:20", "is_generic": False}
    ]
    tracker.commit_channel_watermark(channel, prev_scan_messages, ["frame_hash_123"])

    # Test 1: Next day António says "Bom dia" (generic greeting)
    day2_greeting = [
        {"sender": "antonio", "text": "Bom dia", "time": "09:00", "is_generic": True}
    ]
    reached, reason = tracker.is_watermark_reached(channel, day2_greeting, "hash_different")
    assert not reached, f"Should NOT stop when Antonio just says 'Bom dia'! Got: {reason}"
    print("PASS 1: Antonio saying 'Bom dia' correctly ignored (did NOT false-positive stop).")

    # Test 2: Next day scrolling up encounters Antonio saying "ABCDE"
    day2_boundary = [
        {"sender": "carlos", "text": "Ola pessoal", "time": "15:00", "is_generic": True},
        {"sender": "antonio", "text": "ABCDE", "time": "14:20", "is_generic": False}
    ]
    reached, reason = tracker.is_watermark_reached(channel, day2_boundary, "hash_different")
    assert reached, "Should STOP when encountering Antonio saying 'ABCDE'!"
    print(f"PASS 2: Correctly stopped at boundary: {reason}")

    # Test 3: Composite chain match (Bruno: Bom dia + Antonio: ABCDE)
    day2_chain = [
        {"sender": "bruno", "text": "Bom dia", "time": "14:15", "is_generic": True},
        {"sender": "antonio", "text": "outra coisa", "time": "14:20", "is_generic": False}
    ]
    reached, reason = tracker.is_watermark_reached(channel, day2_chain, "hash_different")
    assert reached, "Should STOP when 2 distinct senders from anchor chain match together!"
    print(f"PASS 3: Composite chain match correctly stopped: {reason}")

    # Clean up
    if test_file.exists():
        test_file.unlink()

    print("\nALL ANTI-FALSE-POSITIVE WATERMARK TESTS PASSED 100%!")

if __name__ == "__main__":
    test_watermark_anti_false_positive()
