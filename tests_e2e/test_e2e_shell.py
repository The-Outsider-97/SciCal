"""The desktop app opens the calculator from its own start page, a different site from the engine. That used to land on the lock screen
(a SameSite=Strict cookie is not sent when a cross-site page starts the navigation)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
    from .test_e2e import ROOT, sync_playwright
except ImportError:
    from test_e2e import ROOT, sync_playwright


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class OpenedFromAnotherSite(unittest.TestCase):
    def test_the_app_window_reaches_the_calculator_not_the_lock_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--agents", "none", "--ready-line", "--port", "0", "--workers", "1",
                                     "--data-dir", tmp + "/d", "--output-dir", tmp + "/o"], cwd=ROOT, stdout=subprocess.PIPE, text=True,
                                    env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])})
            try:
                info = None
                for line in proc.stdout:
                    if line.startswith("SCICAL_READY "):
                        info = json.loads(line[len("SCICAL_READY "):])
                        break
                self.assertIsNotNone(info, "the engine printed its ready line")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    page = browser.new_page()
                    page.route("http://splash.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body="<p>starting</p>"))
                    page.goto("http://splash.test/")
                    page.evaluate("u => window.location.replace(u)", info["url"])        # what the desktop shell does
                    page.wait_for_selector(".topbar", timeout=15000)
                    self.assertIn("SciCal", page.title())
                    browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
