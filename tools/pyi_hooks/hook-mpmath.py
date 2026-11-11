# PyInstaller hook: mpmath without its tests.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("mpmath", filter=lambda name: ".tests" not in name)
datas = collect_data_files("mpmath", excludes=["**/tests/**"])
