"""Browser tests for the SLAI STEM agent features, with the test STEM agent (tests/fake_stem.py) behind the server, and once with agents off.

    python3 -m unittest tests_e2e.test_e2e_stem -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

try:
    from .test_e2e import ROOT, TOKEN, free_port, sync_playwright
except ImportError:
    from test_e2e import ROOT, TOKEN, free_port, sync_playwright


class Base(unittest.TestCase):
    AGENTS = "auto"
    ENV: dict = {}
    shots: Path | None = Path(os.environ["SCICAL_SHOTS"]) if os.environ.get("SCICAL_SHOTS") else None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--port", str(cls.port), "--token", TOKEN, "--data-dir", cls.tmp.name + "/data",
                                     "--output-dir", cls.tmp.name + "/out", "--agents", cls.AGENTS], cwd=ROOT, env={**os.environ, **cls.ENV},
                                    stdout=open(cls.tmp.name + "/server.log", "w"), stderr=subprocess.STDOUT)
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
        cls.tmp.cleanup()

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        self.page = self.ctx.new_page()
        self.problems: list[str] = []
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        self.page.goto(f"{self.base}/?token={TOKEN}")
        self.page.wait_for_selector(".topbar")
        self.fresh()

    def fresh(self):
        """Every test starts from the default setting and an empty worksheet (the server keeps both between tests)."""
        self.page.evaluate("""async () => {
            const h = {'X-SLAI-SciCal': '1', 'Content-Type': 'application/json'};
            const r = await fetch('/api/sessions', {method: 'POST', headers: h, body: JSON.stringify({name: 'test ' + Date.now()})});
            const id = (await r.json()).data.id;
            await fetch('/api/prefs', {method: 'PUT', headers: h, body: JSON.stringify({stemVerify: 'ask', workspace: 'math', reducedMotion: false, lastSession: id})});
        }""")
        self.page.reload()
        self.page.wait_for_selector(".topbar")

    def tearDown(self):
        self.ctx.close()
        self.assertEqual(self.problems, [], "the page reported errors")

    def tab(self, ident: str):
        self.page.locator(f"#tab-{ident}").click()
        self.page.wait_for_selector(f"#tab-{ident}[aria-selected=true]")
        self.page.wait_for_timeout(500)

    def calc(self, text: str):
        self.tab("math")
        box = self.page.locator("textarea[aria-label='Expression to calculate']")
        box.fill(text)
        box.press("Enter")
        self.page.wait_for_timeout(800)

    def shot(self, name: str):
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(self.shots / f"{name}.png"))


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class WithAgent(Base):
    ENV = {"SCICAL_STEM_PROVIDER": "tests.fake_stem:make", "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def test_check_a_calculation(self):
        self.calc("integral(x^2, x, 0, 3)")
        card = self.page.locator(".entry").last
        self.assertNotIn("STEM", card.inner_text())                                       # nothing is claimed before the person asks
        card.get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.wait_for_selector(".stem-panel")
        text = self.page.locator(".stem-panel").inner_text()
        self.assertIn("agrees", text)
        self.assertIn("numerical_methods.adaptive_quadrature", text)
        self.assertIn("STEM ✓ agrees", self.page.locator(".entry").last.inner_text())
        self.shot("stem-check-math")

    def test_the_check_is_kept_in_the_worksheet(self):
        self.calc("mean([1,2,3,4,10])")
        self.page.locator(".entry").last.get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.wait_for_selector(".stem-badge")
        self.page.wait_for_timeout(1500)                                                  # the worksheet autosaves
        self.page.reload()
        self.page.wait_for_selector(".entry")
        self.assertIn("STEM ✓ agrees", self.page.locator(".entry").last.inner_text())

    def test_a_check_that_cannot_run_says_why(self):
        self.calc("a := 5")
        self.page.locator(".entry").last.get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.wait_for_selector(".stem-panel")
        self.assertIn("definition has no value", self.page.locator(".stem-panel").inner_text().lower())

    def test_measurement_result_has_a_check(self):
        self.tab("measurement")
        self.page.get_by_role("button", name="Repeated measurements").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector(".stem-btn")
        self.page.locator(".stem-btn").click()
        self.page.wait_for_selector(".stem-panel")
        text = self.page.locator(".stem-panel").inner_text()
        self.assertIn("Mean", text)
        self.assertIn("statistics.mean", text)
        self.shot("stem-check-measurement")

    def test_operations_without_a_second_route_have_no_button(self):
        self.tab("chemistry")
        self.page.get_by_role("button", name="Molar mass", exact=False).first.click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector(".result")
        self.page.wait_for_timeout(500)
        self.assertEqual(self.page.locator(".stem-btn").count(), 0)

    def test_automatic_checks(self):
        self.page.locator("button[aria-label='Settings']").click()
        self.page.get_by_label("STEM checks").select_option("auto")
        self.page.keyboard.press("Escape")
        self.calc("sqrt(2)*3")
        self.page.wait_for_selector(".stem-badge", timeout=8000)
        self.assertIn("agrees", self.page.locator(".stem-badge").last.inner_text())

    def test_checks_can_be_switched_off(self):
        self.page.locator("button[aria-label='Settings']").click()
        self.page.get_by_label("STEM checks").select_option("off")
        self.page.keyboard.press("Escape")
        self.calc("1+1")
        self.assertEqual(self.page.locator("button[aria-label^='Check this result with the SLAI STEM agent']").count(), 0)

    def test_stem_lab_runs_and_draws(self):
        self.tab("stem")
        self.page.wait_for_selector(".stem-banner strong")
        self.assertIn("connected", self.page.locator(".stem-banner").inner_text())
        self.page.get_by_role("button", name="Differential equations").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector("svg.chart")
        self.assertTrue(self.page.locator("svg.chart").count() >= 2)                      # the solution and the phase portrait
        self.assertIn("final state", self.page.locator(".out").inner_text().lower())
        self.shot("stem-lab-ode")

    def test_stem_lab_every_operation_opens(self):
        self.tab("stem")
        for name in ("Differential equations", "Monte-Carlo uncertainty", "Numerical integration", "Root finding", "Linear systems and conditioning", "Interpolation", "Bootstrap interval", "What the agent offers"):
            self.page.get_by_role("button", name=name).first.click()
            self.page.wait_for_timeout(150)
            self.assertIn(name, self.page.locator(".card-head h2").first.inner_text())

    def test_stem_lab_result_can_go_to_the_worksheet(self):
        self.tab("stem")
        self.page.get_by_role("button", name="Root finding").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector(".result .kv")
        self.page.get_by_role("button", name="Add to worksheet").click()
        self.page.wait_for_timeout(500)
        self.assertTrue(self.page.locator(".saved-list li").count() >= 1)

    @unittest.skipUnless(Base.shots, "set SCICAL_SHOTS to a folder to take the documentation screenshots")
    def test_documentation_screenshots(self):
        self.page.set_viewport_size({"width": 1440, "height": 1300})
        self.tab("stem")
        for op, name in (("Differential equations", "stem-lab-ode"), ("Monte-Carlo uncertainty", "stem-lab-montecarlo"), ("Numerical integration", "stem-lab-quadrature"),
                         ("Root finding", "stem-lab-roots"), ("Linear systems and conditioning", "stem-lab-linear"), ("Interpolation", "stem-lab-interpolation"),
                         ("Bootstrap interval", "stem-lab-bootstrap")):
            self.page.get_by_role("button", name=op).first.click()
            self.page.get_by_role("button", name="Load example").click()
            self.page.wait_for_selector(".result .kv, .result .tablebox")
            self.page.wait_for_timeout(700)
            self.shot(name)
        self.calc("integral(x^2, x, 0, 3)")
        self.calc("diff(x^3*sin(x), x)")
        self.page.locator(".entry").nth(0).get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.locator(".entry").nth(1).get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.wait_for_timeout(1200)
        self.shot("stem-check-math")

    def test_assistant_panel_reports_the_agent(self):
        self.page.locator("button[aria-label='SLAI assistant']").click()
        self.page.wait_for_selector("dialog[open] .stem-assist")
        self.assertIn("Connected to the SLAI STEM agent", self.page.locator("dialog[open]").inner_text())

    def test_narrow_screen_has_no_sideways_scroll(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.tab("stem")
        self.page.get_by_role("button", name="Differential equations").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector("svg.chart")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 392)


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class AgentsOff(Base):
    AGENTS = "none"

    def test_banner_and_check_explain_why_not(self):
        self.tab("stem")
        self.page.wait_for_selector(".stem-banner strong")
        self.assertIn("not available", self.page.locator(".stem-banner").inner_text())
        self.assertIn("--agents none", self.page.locator(".stem-banner").inner_text())
        self.calc("2+2")
        self.page.locator(".entry").last.get_by_role("button", name="Check this result with the SLAI STEM agent").click()
        self.page.wait_for_selector(".toast")
        self.assertIn("--agents none", self.page.locator(".toast").last.inner_text())
        self.assertEqual(self.page.locator(".stem-badge").count(), 0)

    def test_lab_shows_the_reason_as_an_error_card(self):
        self.tab("stem")
        self.page.get_by_role("button", name="Root finding").click()
        self.page.get_by_role("button", name="Load example").click()
        self.page.wait_for_selector(".note-line.error")
        self.assertIn("--agents none", self.page.locator(".note-line.error").inner_text())


if __name__ == "__main__":
    unittest.main()
