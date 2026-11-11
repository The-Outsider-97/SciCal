"""The installed app runs SciCal inside the SLAI checkout's Python environment, and says plainly when it cannot (no quiet fallback)."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scical import linked
from scical.linked import LinkedError, find_linked, run_linked


def make_checkout(tmp: Path, scical_main: str, with_venv: bool = True) -> Path:
    root = tmp / "SLAI"
    (root / "src" / "utils").mkdir(parents=True)
    (root / "src" / "utils" / "sldc.py").write_text("")
    pkg = root / "applications" / "SciCal" / "scical"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(scical_main)
    if with_venv:
        (root / "venv" / "bin").mkdir(parents=True)
        (root / "venv" / "bin" / "python").symlink_to(sys.executable)
        (root / "venv" / "Scripts").mkdir()
        (root / "venv" / "Scripts" / "python.exe").symlink_to(sys.executable)
    return root


@unittest.skipIf(os.name == "nt", "builds a POSIX-style test checkout")
class LinkedLaunch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "install"
        self.base.mkdir()

    def point_at(self, root: Path) -> None:
        (self.base / "slai_root.txt").write_text(str(root))

    def test_no_note_and_no_variable_is_a_clear_error(self):
        with self.assertRaises(LinkedError) as cm:
            find_linked(self.base, {})
        self.assertIn("could not find your SLAI folder", str(cm.exception))

    def test_a_moved_checkout_is_a_clear_error(self):
        (self.base / "slai_root.txt").write_text(str(Path(self.tmp.name) / "gone"))
        with self.assertRaises(LinkedError):
            find_linked(self.base, {})

    def test_a_checkout_without_its_python_environment_says_so(self):
        self.point_at(make_checkout(Path(self.tmp.name), "", with_venv=False))
        with self.assertRaises(LinkedError) as cm:
            find_linked(self.base, {})
        self.assertIn("venv", str(cm.exception))

    def test_runs_scical_in_the_checkout_and_passes_the_ready_line_on(self):
        root = make_checkout(Path(self.tmp.name), 'import os, sys\nprint("SCICAL_READY " + os.environ["SLAI_ROOT"] + " " + " ".join(sys.argv[1:]), flush=True)\n')
        self.point_at(root)
        out = io.StringIO()
        with redirect_stdout(out):
            code = run_linked(["--no-browser", "--ready-line"], self.base, dict(os.environ))
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), f"SCICAL_READY {root.resolve()} --no-browser --ready-line")

    def test_the_environment_variable_wins_over_the_note(self):
        root = make_checkout(Path(self.tmp.name), "")
        env = dict(os.environ, SLAI_ROOT=str(root))
        self.assertEqual(find_linked(self.base, env)[1], root.resolve())

    def test_a_crash_before_ready_is_an_error_not_a_silent_switch(self):
        self.point_at(make_checkout(Path(self.tmp.name), "import sys\nsys.exit(3)\n"))
        with self.assertRaises(LinkedError) as cm, redirect_stdout(io.StringIO()):
            run_linked([], self.base, dict(os.environ))
        self.assertIn("exit code 3", str(cm.exception))


class LauncherEntry(unittest.TestCase):
    def test_the_entry_script_reports_a_failure_as_a_line_the_app_shows(self):
        import subprocess
        env = {k: v for k, v in os.environ.items() if k != "SLAI_ROOT"}
        env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parent.parent), env.get("PYTHONPATH", "")])
        done = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "tools" / "engine_entry.py")], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stdout.startswith("SCICAL_ERROR "), done.stdout)


if __name__ == "__main__":
    unittest.main()
