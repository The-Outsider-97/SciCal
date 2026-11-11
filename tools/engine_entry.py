"""Entry point of the installed Windows app's engine launcher. Kept outside the package so PyInstaller can use it as a script.

SciCal's selling point is the SLAI integration, so the installed app runs SciCal inside the SLAI checkout's own Python environment (see
``scical/linked.py``). If that cannot be done it reports why (``SCICAL_ERROR`` line, shown in the app's window) instead of quietly running
without SLAI."""
import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if os.environ.get("SCICAL_FROZEN_ONLY"):                   # development only: the frozen engine on its own, no SLAI
        from scical.__main__ import main
        sys.exit(main())
    from scical.linked import LinkedError, run_linked
    try:
        sys.exit(run_linked(sys.argv[1:]))
    except LinkedError as exc:
        print(f"SCICAL_ERROR {exc}", flush=True)
        print(f"SciCal: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)
