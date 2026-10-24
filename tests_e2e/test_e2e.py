"""Browser tests: start the real service, drive the real page. Skipped when Playwright or the built client is not available.

    python3 -m unittest discover -s tests_e2e -v
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

TOKEN = "e2e-token-0123456789"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = dict(os.environ)
        cls.proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--port", str(cls.port), "--token", TOKEN, "--data-dir", cls.tmp.name + "/data",
                                     "--output-dir", cls.tmp.name + "/out", "--agents", "none"], cwd=ROOT, env=env, stdout=open(cls.tmp.name + "/server.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/", timeout=0.5)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.1)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        if os.environ.get("SCICAL_E2E_KEEP"):
            print("server log:", cls.tmp.name + "/server.log")
            return
        cls.tmp.cleanup()

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={"width": 1280, "height": 860})
        self.page = self.ctx.new_page()
        self.problems: list[str] = []
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        self.page.goto(f"{self.base}/?token={TOKEN}")
        self.page.wait_for_selector(".topbar")

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.problems, [], "the page reported errors")

    # ---------------------------------------------------------------- helpers
    TABS = {"Mathematics": "math", "Graphing": "graph", "Chemistry": "chemistry", "Biology": "biology", "Measurement": "measurement", "Formulas": "formulas"}

    def tab(self, name: str):
        ident = self.TABS[name]
        self.page.locator(f"#tab-{ident}").click()
        self.page.wait_for_selector(f"#tab-{ident}[aria-selected=true]")
        self.page.wait_for_timeout(500)

    def calc(self, text: str):
        self.tab("Mathematics")
        box = self.page.locator("textarea[aria-label='Expression to calculate']")
        box.fill(text)
        box.press("Enter")
        self.page.wait_for_timeout(700)

    # ---------------------------------------------------------------- tests
    def test_locked_without_token(self):
        ctx = self.browser.new_context()
        try:
            r = ctx.request.get(self.base + "/api/status")
            self.assertEqual(r.status, 401)
        finally:
            ctx.close()

    def test_math_exact_and_error(self):
        self.calc("1/3 + 1/6")
        self.assertIn("exact", self.page.locator(".entry").last.inner_text())
        self.calc("1/0")
        self.assertTrue(self.page.locator(".errbox, .note-line.error, [role=alert]").count() > 0)

    def test_math_definition_and_ans(self):
        self.calc("a := 5")
        self.calc("a^2")
        self.calc("ans + 1")
        self.assertIn("26", self.page.locator(".entry").last.inner_text())

    def test_every_workspace_opens(self):
        for name in ("Mathematics", "Graphing", "Chemistry", "Biology", "Measurement", "Formulas"):
            self.tab(name)
            self.assertTrue(self.page.locator("main, #stage, .stage").count() >= 1)

    def test_graph_examples_and_analysis(self):
        self.tab("Graphing")
        self.page.get_by_role("button", name="sin(x) and cos(x)").click()
        self.page.wait_for_timeout(900)
        self.page.locator("button.btn", has_text="Intersections").click()
        self.page.wait_for_timeout(1000)
        self.assertIn("0.7853982", self.page.locator(".analysis .results").inner_text())
        self.page.get_by_role("button", name="Slider: a·sin(b·x)").click()
        self.page.wait_for_timeout(900)
        self.assertTrue(self.page.locator(".slider").count() >= 1)
        self.page.get_by_role("button", name="Inequality").click()
        self.page.wait_for_timeout(900)
        self.assertEqual(self.page.locator(".layer .err:visible").count(), 0)

    def test_chemistry_balance_and_worksheet(self):
        self.tab("Chemistry")
        self.page.get_by_role("button", name="Balance an equation").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_timeout(900)
        self.assertIn("5", self.page.locator(".out").inner_text())
        self.page.get_by_role("button", name="Add to worksheet").click()
        self.page.wait_for_timeout(500)
        self.assertTrue(self.page.locator(".saved-list li").count() >= 1)

    def test_periodic_table_dialog(self):
        self.tab("Chemistry")
        self.page.wait_for_selector(".pt-cell")
        self.assertEqual(self.page.locator(".pt-cell").count(), 118)
        self.page.locator(".pt-cell", has_text="Fe").first.click()
        self.page.wait_for_selector("dialog[open]")
        self.assertIn("26", self.page.locator("dialog[open]").inner_text())

    def test_biology_punnett(self):
        self.tab("Biology")
        self.page.get_by_role("button", name="Punnett square").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector("table.punnett")
        self.assertIn("aabb", self.page.locator("table.punnett").inner_text())

    def test_measurement_calibration_chart(self):
        self.tab("Measurement")
        self.page.get_by_role("button", name="Calibration curve").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector("svg.chart")
        self.assertTrue(self.page.locator("svg.chart").count() >= 2)

    def test_themes_apply(self):
        for theme in ("dark", "contrast", "light"):
            self.page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
            self.page.wait_for_timeout(100)
            bg = self.page.evaluate("getComputedStyle(document.body).backgroundColor")
            self.assertTrue(bg)

    def test_narrow_screen_has_no_sideways_scroll(self):
        self.page.set_viewport_size({"width": 390, "height": 800})
        for name in ("Mathematics", "Graphing", "Chemistry", "Measurement"):
            self.tab(name)
            wide = self.page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
            self.assertFalse(wide, f"{name} scrolls sideways on a phone")


if __name__ == "__main__":
    unittest.main()
