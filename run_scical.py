"""Start SciCal from the SLAI folder:  python applications/scical/run_scical.py  (same as  python -m scical  inside applications/scical)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    from scical.__main__ import main
    raise SystemExit(main())
