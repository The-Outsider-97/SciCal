# PyInstaller hook: everything SymPy needs at run time, without its test suites and benchmarks (they are most of its size).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("sympy", filter=lambda name: ".tests" not in name and ".benchmarks" not in name and not name.endswith(".conftest"))
datas = collect_data_files("sympy", excludes=["**/tests/**", "**/benchmarks/**"])
