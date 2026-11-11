"""The STEM routes of the real server, started with the test STEM agent (``tests/fake_stem.py``) and, separately, with agents switched off."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from . import test_server as TS
except ImportError:
    import test_server as TS

MARK, ROOT, TOKEN, free_port = TS.MARK, TS.ROOT, TS.TOKEN, TS.free_port


def start(tmp, agents, env_extra):
    port = free_port()
    log = open(Path(tmp) / f"server-{port}.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--port", str(port), "--token", TOKEN, "--data-dir", tmp + f"/data{port}", "--output-dir", tmp + "/out",
                             "--agents", agents, "--workers", "2", "--timeout", "10"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **env_extra},
                             creationflags=TS.SERVER_PROCESS_FLAGS)
    return port, proc, log


class Base(unittest.TestCase):
    AGENTS = "auto"
    ENV: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port, cls.proc, cls.log = start(cls.tmp.name, cls.AGENTS, cls.ENV)
        for _ in range(100):
            try:
                TS.ServerTests.raw.__func__(cls, "GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        _, headers, _ = TS.ServerTests.raw.__func__(cls, "GET", f"/?token={TOKEN}")
        cls.cookie = next(v for k, v in headers if k.lower() == "set-cookie").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        try:
            TS.stop_test_server(cls.proc)
        finally:
            cls.log.close()
            cls.tmp.cleanup()

    @classmethod
    def raw(cls, *a, **kw):
        return TS.ServerTests.raw.__func__(cls, *a, **kw)

    def call(self, method, path, body=None):
        status, _, data = self.raw(method, path, body, {"Cookie": self.cookie, **MARK})
        return status, json.loads(data)


class WithAgent(Base):
    ENV = {"SCICAL_STEM_PROVIDER": "tests.fake_stem:make", "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def test_status(self):
        s, r = self.call("GET", "/api/stem/status")
        self.assertEqual(s, 200)
        self.assertTrue(r["data"]["available"])
        self.assertIn("statistics", r["data"]["domains"])

    def test_verify_a_calculation(self):
        s, r = self.call("POST", "/api/stem/verify", {"entry": {"kind": "calc", "input": "integral(x^2, x, 0, 3)"}, "settings": {"angle": "rad"}, "context": []})
        self.assertEqual(s, 200, r)
        v = r["data"]
        self.assertEqual(v["verdict"], "agree")
        self.assertEqual(v["checks"][0]["via"], "numerical_methods.adaptive_quadrature")

    def test_verify_uses_the_worksheet_context_and_settings(self):
        s, r = self.call("POST", "/api/stem/verify", {"entry": {"kind": "calc", "input": "a*sin(30)"}, "settings": {"angle": "deg"}, "context": ["a := 4"]})
        self.assertEqual(r["data"]["verdict"], "agree")
        self.assertEqual(r["data"]["checks"][0]["scical"], "2")

    def test_verify_a_workspace_result_computes_it_when_missing(self):
        s, r = self.call("POST", "/api/stem/verify", {"entry": {"kind": "domain", "domain": "measurement", "op": "repeated", "params": {"values": [9.81, 9.79, 9.84, 9.8, 9.83]}}})
        self.assertEqual(r["data"]["verdict"], "agree", r)

    def test_verify_validates_its_input(self):
        for body in ({"entry": "x"}, {"entry": {"kind": "bogus"}}, {"entry": {"kind": "calc", "input": "1"}, "context": "nope"}, {}):
            with self.subTest(body):
                s, r = self.call("POST", "/api/stem/verify", body)
                self.assertEqual(s, 400, r)

    def test_stem_lab_through_the_domain_route(self):
        s, r = self.call("POST", "/api/domain", {"domain": "stem", "op": "roots", "params": {"expression": "x^2 - 2 = 0", "a": "0", "b": "2"}, "settings": {}})
        self.assertEqual(s, 200)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["root"]["value"], 2 ** 0.5, places=8)

    def test_stem_lab_input_error_is_an_error_card(self):
        s, r = self.call("POST", "/api/domain", {"domain": "stem", "op": "ode", "params": {"equations": "nonsense", "initial": {"x": "1"}, "t1": "1"}, "settings": {}})
        self.assertEqual(s, 200)
        self.assertFalse(r["ok"])

    def test_preferences_accept_the_stem_settings(self):
        s, r = self.call("PUT", "/api/prefs", {"stemVerify": "auto", "workspace": "stem"})
        self.assertEqual(s, 200, r)
        s, r = self.call("PUT", "/api/prefs", {"stemVerify": "sometimes"})
        self.assertEqual(s, 400)

    def test_worksheet_keeps_the_verification_and_exports_it(self):
        _, r = self.call("POST", "/api/sessions", {"name": "stem"})
        sid = r["data"]["id"]
        entry = {"kind": "calc", "input": "mean([1,2,3])", "result": {"ok": True, "value": {"text": "2", "latex": "2"}},
                 "verification": {"ran": True, "verdict": "agree", "summary": "x", "counts": {"agree": 1, "differ": 0}, "checks": []}}
        s, r = self.call("PUT", f"/api/sessions/{sid}", {"entries": [entry]})
        self.assertEqual(s, 200, r)
        _, r = self.call("GET", f"/api/sessions/{sid}")
        self.assertEqual(r["data"]["entries"][0]["verification"]["verdict"], "agree")
        s, headers, data = self.raw("POST", "/api/export", {"sessionId": sid, "format": "txt"}, {"Cookie": self.cookie, **MARK})
        self.assertEqual(s, 200)
        self.assertIn(b"STEM check", data)


class AgentsOff(Base):
    AGENTS = "none"

    def test_status_says_why(self):
        _, r = self.call("GET", "/api/stem/status")
        self.assertFalse(r["data"]["available"])
        self.assertIn("--agents none", r["data"]["reason"])

    def test_verify_answers_instead_of_failing(self):
        s, r = self.call("POST", "/api/stem/verify", {"entry": {"kind": "calc", "input": "1+1"}})
        self.assertEqual(s, 200)
        self.assertEqual(r["data"]["verdict"], "unavailable")
        self.assertFalse(r["data"]["ran"])

    def test_stem_lab_reports_the_reason(self):
        _, r = self.call("POST", "/api/domain", {"domain": "stem", "op": "catalogue", "params": {}})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "stem_unavailable")


if __name__ == "__main__":
    unittest.main()
