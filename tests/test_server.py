"""The HTTP service: who may talk to it, what it refuses, and the worksheet life cycle. Starts the real server on a free port."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "unit-test-token-0123456789"
MARK = {"X-SLAI-SciCal": "1", "Content-Type": "application/json"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.log = open(Path(cls.tmp.name) / "server.log", "w")
        cls.proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--port", str(cls.port), "--token", TOKEN, "--data-dir", cls.tmp.name + "/data",
                                     "--output-dir", cls.tmp.name + "/out", "--agents", "none", "--workers", "2", "--timeout", "5"], cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                cls.raw("GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        status, headers, _ = cls.raw("GET", f"/?token={TOKEN}")
        cookie = next((v for k, v in headers if k.lower() == "set-cookie"), "")
        cls.cookie = cookie.split(";")[0]
        cls.set_cookie = cookie

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.log.close()
        cls.tmp.cleanup()

    @classmethod
    def raw(cls, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=15)
        h = dict(headers or {})
        if host:
            h["Host"] = host
        try:
            c.putrequest(method, path, skip_host=bool(host), skip_accept_encoding=True)
            if host:
                c.putheader("Host", host)
            for k, v in h.items():
                if k != "Host":
                    c.putheader(k, v)
            data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
            if data is not None:
                c.putheader("Content-Length", str(len(data)))
            try:
                c.endheaders(data)
            except (BrokenPipeError, ConnectionResetError):
                pass                                    # the server refused an oversized body and hung up early; its answer is still readable
            r = c.getresponse()
            return r.status, r.getheaders(), r.read()
        finally:
            c.close()

    def call(self, method, path, body=None, extra=None):
        h = {"Cookie": self.cookie, **MARK, **(extra or {})}
        status, headers, data = self.raw(method, path, body, h)
        try:
            return status, json.loads(data), dict(headers)
        except ValueError:
            return status, data, dict(headers)

    # ------------------------------------------------------------------ who may talk to it
    def test_no_token_no_access(self):
        for path in ("/api/status", "/api/sessions", "/api/prefs", "/"):
            with self.subTest(path):
                status, _, _ = self.raw("GET", path)
                self.assertIn(status, (401, 403))

    def test_wrong_token_is_refused(self):
        status, _, _ = self.raw("GET", "/?token=nope")
        self.assertIn(status, (401, 403))
        status, _, _ = self.raw("GET", "/api/status", headers={"Cookie": "slai_scical_token=nope"})
        self.assertIn(status, (401, 403))

    def test_cookie_is_httponly_and_samesite(self):
        self.assertIn("HttpOnly", self.set_cookie)
        self.assertIn("SameSite=Strict", self.set_cookie)
        self.assertIn("Path=/", self.set_cookie)

    def test_foreign_host_header_is_refused(self):                          # DNS rebinding
        status, _, _ = self.raw("GET", "/api/status", headers={"Cookie": self.cookie}, host="evil.example")
        self.assertIn(status, (400, 401, 403))

    def test_foreign_origin_and_missing_marker_are_refused(self):
        body = {"input": "1+1"}
        status, _, _ = self.raw("POST", "/api/calc", body, {"Cookie": self.cookie, "Content-Type": "application/json"})                    # no marker
        self.assertIn(status, (400, 401, 403))
        status, _, _ = self.raw("POST", "/api/calc", body, {"Cookie": self.cookie, **MARK, "Origin": "http://evil.example"})
        self.assertIn(status, (400, 401, 403))
        status, _, _ = self.raw("POST", "/api/calc", body, {"Cookie": self.cookie, **MARK, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)

    def test_security_headers(self):
        _, headers, _ = self.raw("GET", "/api/status", headers={"Cookie": self.cookie})
        h = {k.lower(): v for k, v in headers}
        csp = h["content-security-policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "no-store")
        self.assertNotIn("access-control-allow-origin", h)

    def test_no_cors_preflight(self):
        status, headers, _ = self.raw("OPTIONS", "/api/calc", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", {k.lower() for k, _ in headers})
        self.assertNotEqual(status, 200)

    # ------------------------------------------------------------------ files
    def test_client_files_are_served_and_traversal_is_not(self):
        status, headers, body = self.raw("GET", "/", headers={"Cookie": self.cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"<script", body)
        self.assertNotIn(b"<script>", body)                                 # no inline script (the CSP would block it)
        for path in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/js/../../scical/__init__.py", "/js/..%2f..%2fscical/__init__.py", "/%00", "//etc/passwd"):
            with self.subTest(path):
                status, _, body = self.raw("GET", path, headers={"Cookie": self.cookie})
                self.assertNotEqual(status, 200)
                self.assertNotIn(b"root:", body)

    # ------------------------------------------------------------------ compute
    def test_calc_round_trip(self):
        status, r, _ = self.call("POST", "/api/calc", {"input": "1/3 + 1/6", "settings": {}})
        self.assertEqual(status, 200)
        self.assertTrue(r["ok"])
        self.assertEqual(r["value"]["text"], "1 / 2")

    def test_math_error_is_http_200_with_an_error_body(self):
        status, r, _ = self.call("POST", "/api/calc", {"input": "x+"})
        self.assertEqual(status, 200)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "parse_error")

    def test_bad_requests(self):
        status, _, _ = self.raw("POST", "/api/calc", b"{not json", {"Cookie": self.cookie, **MARK})
        self.assertEqual(status, 400)
        status, _, _ = self.raw("POST", "/api/calc", b"[]", {"Cookie": self.cookie, **MARK})
        self.assertEqual(status, 400)
        status, _, _ = self.raw("POST", "/api/calc", b'{"input": "' + b"1" * 3_000_000 + b'"}', {"Cookie": self.cookie, **MARK})
        self.assertEqual(status, 413)
        status, _, _ = self.call("GET", "/api/nope")
        self.assertEqual(status, 404)
        status, _, _ = self.call("DELETE", "/api/calc")
        self.assertIn(status, (400, 404, 405))
        status, r, _ = self.call("POST", "/api/calc", {"input": "1", "jobId": "bad id!"})
        self.assertEqual(status, 400)

    def test_runaway_calculation_is_stopped_and_the_service_survives(self):
        t0 = time.time()
        status, r, _ = self.call("POST", "/api/calc", {"input": "integral(sin(x^7)/x^3 * exp(x*sin(x)), x, 0, 50)"})
        self.assertIn(status, (200, 408))
        if status == 408:
            self.assertEqual(r["error"]["code"], "timeout")
        self.assertLess(time.time() - t0, 20)
        status, r, _ = self.call("POST", "/api/calc", {"input": "2+2"})
        self.assertEqual(r["value"]["text"], "4")

    def test_domain_and_graph_endpoints(self):
        status, r, _ = self.call("POST", "/api/domain", {"domain": "chemistry", "op": "molar_mass", "params": {"formula": "H2O"}})
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["molarMass"]["value"], 18.015, places=2)
        status, r, _ = self.call("POST", "/api/graph", {"op": "render", "spec": {"viewport": {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}, "width": 400, "height": 300, "layers": [{"id": "a", "type": "auto", "expr": "x"}]}})
        self.assertTrue(r["ok"])
        status, r, _ = self.call("POST", "/api/domain", {"domain": "../../etc", "op": "x", "params": {}})
        self.assertFalse(r["ok"])

    def test_forms_catalogue(self):
        status, r, _ = self.call("GET", "/api/forms")
        self.assertEqual(sorted(r["data"]["domains"]), ["biology", "chemistry", "formulas", "measurement"])

    # ------------------------------------------------------------------ worksheets
    def test_worksheet_life_cycle(self):
        _, r, _ = self.call("POST", "/api/sessions", {"name": "Lab <1>"})
        sid = r["data"]["id"]
        self.assertRegex(sid, r"^[0-9a-f]{16}$")
        entries = [{"kind": "calc", "input": "1+1", "ok": True, "result": {"ok": True, "value": {"text": "2", "latex": "2"}}}, {"kind": "note", "text": "hello"}]
        status, r, _ = self.call("PUT", f"/api/sessions/{sid}", {"entries": entries})
        self.assertEqual(r["data"]["entries"], 2)
        _, r, _ = self.call("GET", f"/api/sessions/{sid}")
        self.assertEqual([e["kind"] for e in r["data"]["entries"]], ["calc", "note"])
        _, r, _ = self.call("GET", "/api/history/search?q=hello")
        self.assertTrue(r["data"]["hits"])
        _, r, _ = self.call("GET", "/api/sessions")
        self.assertIn(sid, [s["id"] for s in r["data"]["sessions"]])
        status, r, _ = self.call("DELETE", f"/api/sessions/{sid}")
        self.assertTrue(r["data"]["deleted"])
        status, _, _ = self.call("GET", f"/api/sessions/{sid}")
        self.assertEqual(status, 404)

    def test_session_ids_cannot_escape_the_data_folder(self):
        for sid in ("..", "..%2f..%2fetc%2fpasswd", "a%2fb", "%2e%2e", "x" * 200):
            with self.subTest(sid):
                status, _, _ = self.call("GET", f"/api/sessions/{sid}")
                self.assertIn(status, (400, 404))
                status, _, _ = self.call("DELETE", f"/api/sessions/{sid}")
                self.assertIn(status, (400, 404))

    def test_worksheet_survives_hostile_entries(self):
        _, r, _ = self.call("POST", "/api/sessions", {"name": "x"})
        sid = r["data"]["id"]
        hostile = [{"kind": "calc", "input": "<script>alert(1)</script>", "result": {"ok": True, "value": {"text": "<img src=x onerror=alert(1)>", "latex": "\\href{javascript:alert(1)}{x}"}}},
                   {"kind": "nonsense", "text": "x"}, "string", 5, None, {"kind": "note", "text": "y" * 500000}]
        status, r, _ = self.call("PUT", f"/api/sessions/{sid}", {"entries": hostile})
        self.assertIn(status, (200, 400, 413))
        status, r, _ = self.call("GET", f"/api/sessions/{sid}")
        self.assertEqual(status, 200)
        for e in r["data"]["entries"]:
            self.assertIn(e["kind"], ("calc", "domain", "graph", "formula", "note"))
            self.assertLess(len(json.dumps(e)), 400_000)

    def test_exports(self):
        _, r, _ = self.call("POST", "/api/sessions", {"name": "Export me"})
        sid = r["data"]["id"]
        self.call("PUT", f"/api/sessions/{sid}", {"entries": [{"kind": "calc", "input": "=HYPERLINK(\"http://evil\",\"x\")", "ok": True, "result": {"ok": True, "value": {"text": "+1", "latex": "1"}}}, {"kind": "note", "text": "@SUM(1)"}]})
        for fmt, mime in (("md", "text/markdown"), ("txt", "text/plain"), ("csv", "text/csv"), ("json", "application/json")):
            with self.subTest(fmt):
                status, headers, data = self.raw("POST", "/api/export", {"sessionId": sid, "format": fmt}, {"Cookie": self.cookie, **MARK})
                self.assertEqual(status, 200)
                h = {k.lower(): v for k, v in headers}
                self.assertTrue(h["content-type"].startswith(mime))
                self.assertIn("attachment", h["content-disposition"])
                self.assertTrue(data)
        status, _, data = self.raw("POST", "/api/export", {"sessionId": sid, "format": "csv"}, {"Cookie": self.cookie, **MARK})
        import csv, io, re
        for row in list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))[1:]:
            for cell in row:
                if cell[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", cell):
                    self.fail(f"spreadsheet formula injection in {cell!r}")
        status, _, _ = self.raw("POST", "/api/export", {"sessionId": sid, "format": "exe"}, {"Cookie": self.cookie, **MARK})
        self.assertEqual(status, 400)

    def test_crosscheck_answers_in_the_shape_the_client_reads(self):
        status, r, _ = self.call("POST", "/api/assist/crosscheck", {"values": [1.0, 2.0, 3.0, 4.5]})
        self.assertEqual(status, 200)
        d = r["data"]
        self.assertIsInstance(d["ran"], bool)
        if d["ran"]:
            self.assertTrue(d["rows"])
        else:
            self.assertTrue(d["reason"])                # it must say why, never fail silently
        status, r, _ = self.call("POST", "/api/assist/crosscheck", {"values": [1.0]})
        self.assertIn(status, (200, 400))

    def test_table_export(self):
        status, headers, data = self.raw("POST", "/api/export/table", {"name": "t/../x", "columns": ["a", "b"], "rows": [[1, "=2+2"], [3, "x"]]}, {"Cookie": self.cookie, **MARK})
        self.assertEqual(status, 200)
        text = data.decode("utf-8-sig")
        self.assertNotIn(",=2+2", text)
        cd = dict((k.lower(), v) for k, v in headers)["content-disposition"]
        self.assertNotIn("/", cd.split("filename")[1])

    def test_preferences_are_validated(self):
        for bad in ({"fontScale": 99}, {"workspace": "../x"}, {"theme": "<x>"}, {"evil": "x"}):
            with self.subTest(bad):
                _, r, _ = self.call("PUT", "/api/prefs", bad)
                self.assertFalse(r["ok"])
        _, r, _ = self.call("PUT", "/api/prefs", {"theme": "dark", "fontScale": 1.2})
        self.assertEqual((r["data"]["theme"], r["data"]["fontScale"]), ("dark", 1.2))

    def test_assistant_is_off_without_agents(self):
        _, r, _ = self.call("GET", "/api/assist/status")
        self.assertEqual(r["data"]["mode"], "none")


if __name__ == "__main__":
    unittest.main()
