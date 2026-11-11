"""Browser tests for motion in the 3D views and scenes, the reduce-motion switch, and the phone layout.

    python3 -m unittest tests_e2e.test_e2e_motion -v
"""
from __future__ import annotations

import unittest

try:
    from .test_e2e import ROOT, sync_playwright
    from .test_e2e_stem import Base
except ImportError:
    from test_e2e import ROOT, sync_playwright
    from test_e2e_stem import Base


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class Motion(Base):
    AGENTS = "none"

    def graph3d(self):
        self.tab("graph")
        self.page.get_by_role("tab", name="3D", exact=True).click()
        self.page.wait_for_selector("canvas[aria-label^='3D graph']", timeout=15000)
        self.page.wait_for_timeout(800)

    def set_reduced(self, on: bool):
        self.page.evaluate("""async (on) => {
            const h = {'X-SLAI-SciCal': '1', 'Content-Type': 'application/json'};
            await fetch('/api/prefs', {method: 'PUT', headers: h, body: JSON.stringify({reducedMotion: on})});
        }""", on)
        self.page.reload()
        self.page.wait_for_selector(".topbar")

    def pixels(self, selector: str) -> str:
        return self.page.evaluate("(s) => { const c = document.querySelector(s); return c.toDataURL('image/png').length + ':' + c.toDataURL('image/png').slice(-120); }", selector)

    # ------------------------------------------------------------------ 3D graph
    def test_view_presets_glide_and_end_exactly_on_the_view(self):
        self.graph3d()
        canvas = "canvas[aria-label^='3D graph']"
        before = self.pixels(canvas)
        self.page.get_by_role("button", name="Top", exact=True).click()
        self.page.wait_for_timeout(120)
        midway = self.pixels(canvas)
        self.page.wait_for_timeout(1200)
        after = self.pixels(canvas)
        self.assertNotEqual(before, midway, "the picture changed while moving")
        self.assertNotEqual(midway, after, "it was still moving after 120 ms (a glide, not a jump)")
        self.page.wait_for_timeout(300)
        self.assertEqual(after, self.pixels(canvas), "it came to rest")

    def test_spin_turns_the_scene_and_stops(self):
        self.graph3d()
        canvas = "canvas[aria-label^='3D graph']"
        spin = self.page.get_by_role("button", name="Spin", exact=True)
        self.assertEqual(spin.get_attribute("aria-pressed"), "false")
        first = self.pixels(canvas)
        spin.click()
        self.assertEqual(spin.get_attribute("aria-pressed"), "true")
        self.page.wait_for_timeout(700)
        self.assertNotEqual(first, self.pixels(canvas))
        spin.click()
        self.assertEqual(spin.get_attribute("aria-pressed"), "false")
        self.page.wait_for_timeout(200)
        still = self.pixels(canvas)
        self.page.wait_for_timeout(400)
        self.assertEqual(still, self.pixels(canvas), "the scene stopped when Spin was switched off")

    def test_a_flick_keeps_turning_for_a_moment(self):
        self.graph3d()
        # the whole drag runs inside the page, so a slow test machine cannot stretch the gaps between samples
        self.page.evaluate("""async () => {
            const c = document.querySelector("canvas[aria-label^='3D graph']");
            const r = c.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const fire = (type, dx) => c.dispatchEvent(new PointerEvent(type, {pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: x + dx, clientY: y, bubbles: true}));
            fire('pointerdown', 0);
            for (let i = 1; i <= 6; i++) { await new Promise((ok) => setTimeout(ok, 8)); fire('pointermove', 14 * i); }
            fire('pointerup', 84);
        }""")
        released = self.pixels("canvas[aria-label^='3D graph']")
        self.page.wait_for_timeout(150)
        self.assertNotEqual(released, self.pixels("canvas[aria-label^='3D graph']"), "momentum carried on after release")
        self.page.wait_for_timeout(2500)
        rest = self.pixels("canvas[aria-label^='3D graph']")
        self.page.wait_for_timeout(300)
        self.assertEqual(rest, self.pixels("canvas[aria-label^='3D graph']"), "and then it settled")

    def test_a_slider_can_be_played(self):
        self.graph3d()
        self.page.get_by_role("button", name="Slider: a·sin(x)·cos(y)").click()
        self.page.wait_for_selector(".slider")
        play = self.page.locator(".slider").get_by_role("button", name="Play")
        play.wait_for()
        value = self.page.locator(".slider .head span").nth(1)
        start = value.inner_text()
        play.click()
        pause = self.page.locator(".slider").get_by_role("button", name="Pause")
        pause.wait_for()
        self.assertEqual(pause.get_attribute("aria-pressed"), "true")
        self.page.wait_for_timeout(1800)
        moving = value.inner_text()
        self.assertNotEqual(start, moving, "the slider value moved")
        pause.click()
        self.page.wait_for_timeout(500)
        stopped = value.inner_text()
        self.page.wait_for_timeout(500)
        self.assertEqual(stopped, value.inner_text(), "Pause stops it")

    def test_reduced_motion_switches_the_animation_off(self):
        self.set_reduced(True)
        self.graph3d()
        spin = self.page.get_by_role("button", name="Spin", exact=True)
        spin.click()
        self.assertEqual(spin.get_attribute("aria-pressed"), "false", "Spin refuses under reduced motion")
        canvas = "canvas[aria-label^='3D graph']"
        before = self.pixels(canvas)
        self.page.get_by_role("button", name="Front", exact=True).click()
        self.page.wait_for_timeout(60)
        self.assertNotEqual(before, self.pixels(canvas), "the view changed at once, with no glide")
        settled = self.pixels(canvas)
        self.page.wait_for_timeout(300)
        self.assertEqual(settled, self.pixels(canvas))
        self.page.get_by_role("button", name="Slider: a·sin(x)·cos(y)").click()
        self.page.wait_for_selector(".slider")
        self.assertTrue(self.page.locator(".slider").get_by_role("button", name="Play").is_disabled())

    # ------------------------------------------------------------------ chemistry and biology scenes
    def open_atom(self, symbol: str):
        self.tab("chemistry")
        self.page.locator(".pt-cell").filter(has_text=symbol).first.click()
        self.page.wait_for_selector("dialog .science-scene")
        return self.page.locator("dialog .science-scene").first

    def test_atom_scene_plays_smoothly_and_pauses(self):
        scene = self.open_atom("Na")
        canvas = "dialog .science-scene canvas"
        scene.get_by_role("button", name="Play").click()
        a = self.pixels(canvas)
        self.page.wait_for_timeout(250)
        b = self.pixels(canvas)
        self.page.wait_for_timeout(250)
        c = self.pixels(canvas)
        self.assertEqual(len({a, b, c}), 3, "a new picture every few hundred ms (continuous, not 2 steps a second)")
        scene.get_by_role("button", name="Pause").click()
        self.page.wait_for_timeout(100)
        d = self.pixels(canvas)
        self.page.wait_for_timeout(300)
        self.assertEqual(d, self.pixels(canvas))

    def test_molecule_cross_fades_between_the_two_views(self):
        self.tab("chemistry")
        self.page.locator(".opbtn").filter(has=self.page.locator("strong", has_text="Molar mass")).first.click()
        self.page.locator(".domain-main input[type=text]").first.fill("CO2")
        self.page.get_by_role("button", name="Calculate").click()
        self.page.wait_for_selector(".science-scene")
        scene = self.page.locator(".science-scene").first
        canvas = ".science-scene canvas"
        first = self.pixels(canvas)
        scene.get_by_role("button", name="Play").click()
        self.page.wait_for_timeout(450)
        mid = self.pixels(canvas)
        self.page.wait_for_timeout(1800)
        end = self.pixels(canvas)
        self.assertEqual(len({first, mid, end}), 3, "a state in between, then the other view")
        self.assertIn("Space-filling", scene.inner_text())
        self.assertEqual(scene.get_by_role("button", name="Play").count(), 1, "Play is available again at the end")

    def test_pinch_zoom_works_on_a_scene(self):
        scene = self.open_atom("C")
        canvas = "dialog .science-scene canvas"
        before = self.pixels(canvas)
        client = self.page.context.new_cdp_session(self.page)
        box = self.page.locator(canvas).bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        client.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": cx - 30, "y": cy, "id": 1}, {"x": cx + 30, "y": cy, "id": 2}]})
        for step in range(1, 9):
            client.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": cx - 30 - 12 * step, "y": cy, "id": 1}, {"x": cx + 30 + 12 * step, "y": cy, "id": 2}]})
        client.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        self.page.wait_for_timeout(200)
        self.assertNotEqual(before, self.pixels(canvas), "two fingers apart zoomed the scene")


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless((ROOT / "dist" / "index.html").is_file(), "the web client is not built (npm run build)")
class PhoneLayout(Base):
    AGENTS = "none"

    def setUp(self):
        super().setUp()
        self.ctx.close()
        self.ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True)
        self.page = self.ctx.new_page()
        self.problems = []
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        self.page.goto(f"{self.base}/?token=e2e-token-0123456789")
        self.page.wait_for_selector(".topbar")

    def test_tabs_are_a_bottom_bar_with_labels(self):
        tabs = self.page.locator(".tabs").bounding_box()
        self.assertGreater(tabs["y"] + tabs["height"], 840, "the tab bar sits at the bottom of the screen")
        self.assertTrue(self.page.locator("#tab-graph .tt").is_visible(), "each tab has a label")
        top = self.page.locator(".topbar").bounding_box()
        self.assertLess(top["height"], 80, "the top bar is one compact row")

    def test_nothing_scrolls_sideways_in_any_workspace(self):
        for ident in ("math", "graph", "chemistry", "biology", "measurement", "formulas", "stem", "finance", "constants"):
            self.page.locator(f"#tab-{ident}").click()
            self.page.wait_for_timeout(300)
            over = self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            self.assertEqual(over, 0, f"{ident} is wider than the screen by {over}px")

    def test_the_input_stays_reachable_above_the_tab_bar(self):
        run = self.page.get_by_role("button", name="Calculate", exact=True)
        box = run.bounding_box()
        tabs = self.page.locator(".tabs").bounding_box()
        self.assertLess(box["y"] + box["height"], tabs["y"] + 1, "Calculate is not hidden behind the tab bar")
        self.assertLess(box["y"], 844)

    def test_operations_are_one_scrolling_row_and_the_form_is_in_view(self):
        self.page.locator("#tab-chemistry").click()
        self.page.wait_for_timeout(400)
        nav = self.page.locator(".oplist").bounding_box()
        self.assertLess(nav["height"], 90, "the operation list is a single row of chips")
        form = self.page.locator(".domain-main .card").first.bounding_box()
        self.assertLess(form["y"], 300, "the form starts near the top, not after a long list")


if __name__ == "__main__":
    unittest.main()
