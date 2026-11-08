"""scripts/f2_copy_detector.py — thin command-line wrapper; the logic lives in stockbot/data_checks/copy_detector.py (restructure Phase 3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stockbot.data_checks.copy_detector import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
