"""Entry point of the frozen engine (the program the Windows app starts). Kept outside the package so PyInstaller can use it as a script."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()          # the calculation workers are started through this, from inside the frozen program
    from scical.__main__ import main
    sys.exit(main())
