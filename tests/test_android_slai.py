"""What the phone apps carry of SLAI: the file list, and the stand-ins for the two packages Android's Python lacks."""
from __future__ import annotations

import importlib.util
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src-tauri" / "mobile"))
import stage_slai  # noqa: E402


def load_shim():
    spec = importlib.util.spec_from_file_location("scical_shim_special", ROOT / "scical" / "_shims" / "scipy" / "special.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StageSlai(unittest.TestCase):
    def make_root(self, tmp: Path, skip: str | None = None) -> Path:
        files = list(stage_slai.FILES) + [f"{t}/mod.py" for t in stage_slai.TREES] + [
            "src/agents/stem/configs/stem_config.yaml", "src/agents/stem/tests/test_x.py", "src/agents/planning/models/big.json",
            "src/agents/base/__pycache__/x.py", "src/agents/stem/notes.md", "src/utils/test/t.py"]
        for rel in files:
            if rel == skip:
                continue
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x = 1\n")
        for rel in stage_slai.TREES:
            (tmp / rel).mkdir(parents=True, exist_ok=True)
        return tmp

    def test_the_selection_keeps_code_and_settings_and_drops_tests_models_and_caches(self):
        with tempfile.TemporaryDirectory() as t:
            got = {p.as_posix() for p in stage_slai.selection(self.make_root(Path(t)))}
        self.assertIn("src/agents/stem_agent.py", got)
        self.assertIn("src/agents/stem/configs/stem_config.yaml", got)
        self.assertIn("src/utils/mod.py", got)
        for dropped in ("src/agents/stem/tests/test_x.py", "src/agents/planning/models/big.json", "src/agents/base/__pycache__/x.py",
                        "src/agents/stem/notes.md", "src/utils/test/t.py"):
            self.assertNotIn(dropped, got)

    def test_a_checkout_that_lacks_a_required_file_is_an_error_not_a_smaller_app(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.make_root(Path(t), skip="src/agents/stem_agent.py")
            with self.assertRaises(FileNotFoundError):
                stage_slai.selection(root)

    def test_stage_copies_the_selection(self):
        with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as d:
            n = stage_slai.stage(self.make_root(Path(t)), Path(d) / "slai")
            self.assertTrue((Path(d) / "slai" / "src" / "agents" / "stem_agent.py").is_file())
            self.assertGreater(n, 5)


class Shims(unittest.TestCase):
    def test_special_functions_match_scipy(self):
        try:
            import scipy.special as real
        except ImportError:
            self.skipTest("SciPy is not installed here")
        shim = load_shim()
        rnd = random.Random(7)
        for _ in range(300):
            a, b, x, g = 10 ** rnd.uniform(-1, 2), 10 ** rnd.uniform(-1, 2), rnd.random(), 10 ** rnd.uniform(-3, 2)
            for want, got in ((real.betainc(a, b, x), shim.betainc(a, b, x)), (real.gammainc(a, g), shim.gammainc(a, g)), (real.gammaln(a), shim.gammaln(a))):
                self.assertTrue(math.isclose(want, got, rel_tol=1e-9, abs_tol=1e-12), (a, b, x, g, want, got))

    def test_edges(self):
        shim = load_shim()
        self.assertEqual(shim.gammainc(2.0, 0.0), 0.0)
        self.assertTrue(math.isnan(shim.betainc(1.0, 1.0, 1.5)))
        self.assertEqual(shim.gammaln(0.0), math.inf)

    def test_jsonschema_stand_in_refuses_instead_of_pretending(self):
        sys.path.insert(0, str(ROOT / "scical" / "_shims"))
        try:
            spec = importlib.util.spec_from_file_location("js_shim", ROOT / "scical" / "_shims" / "jsonschema" / "__init__.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(str(ROOT / "scical" / "_shims"))
        with self.assertRaises(RuntimeError):
            mod.Draft202012Validator({})


if __name__ == "__main__":
    unittest.main()
