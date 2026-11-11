"""The pieces the phone apps rely on: the thread-based calculation pool and the embedded server (no worker processes, no browser)."""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scical.errors import Cancelled, TimedOut
from scical.services import workers
from scical.services.workers import ThreadPool, make_pool, can_use_processes


class ThreadPoolTests(unittest.TestCase):
    def setUp(self):
        self.pool = ThreadPool(2, default_timeout=5).start()

    def tearDown(self):
        self.pool.close()

    def test_a_calculation_runs_and_returns_the_same_shape_as_the_process_pool(self):
        out = self.pool.submit({"kind": "calc", "input": "2+2"}, "j1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["value"]["text"], "4")
        self.assertEqual(self.pool.status()["mode"], "threads")

    def test_a_failing_task_is_reported_not_raised(self):
        out = self.pool.submit({"kind": "nonsense"}, "j2")
        self.assertFalse(out["ok"])

    def test_a_runaway_calculation_times_out_and_the_pool_keeps_working(self):
        t0 = time.time()
        with mock.patch("scical.services.tasks.run", side_effect=lambda task: [None for _ in iter(int, 1)]):    # pure-Python endless loop
            with self.assertRaises(TimedOut):
                self.pool.submit({"kind": "ping"}, "j3", timeout=0.6)
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(self.pool.status()["stuck"], 0, "the endless loop was stopped, not left running")
        self.assertEqual(self.pool.submit({"kind": "calc", "input": "3*3"}, "j4")["value"]["text"], "9")

    def test_a_calculation_can_be_cancelled(self):
        def spin(_task):
            while True:
                pass
        result: dict = {}

        def go():
            try:
                self.pool.submit({"kind": "ping"}, "j5", timeout=30)
            except Cancelled as exc:
                result["cancelled"] = exc
        with mock.patch("scical.services.tasks.run", side_effect=spin):
            t = threading.Thread(target=go)
            t.start()
            time.sleep(0.4)
            self.assertTrue(self.pool.cancel("j5"))
            t.join(8)
        self.assertIn("cancelled", result)

    def test_auto_mode_picks_threads_only_where_processes_do_not_exist(self):
        with mock.patch.object(workers, "can_use_processes", return_value=False):
            p = make_pool("auto", 1)
            self.assertIsInstance(p, ThreadPool)
            p.close()
        self.assertIsInstance(make_pool("thread", 1), ThreadPool)
        with mock.patch.dict("os.environ", {"SCICAL_NO_PROCESSES": "1"}):
            self.assertFalse(can_use_processes())


class EmbeddedServerTests(unittest.TestCase):
    def test_start_serves_the_app_to_the_returned_address_and_stop_ends_it(self):
        from scical import embed
        with tempfile.TemporaryDirectory() as tmp:
            info = embed.start(tmp + "/data", tmp + "/out", token="embed-token-0123456789")
            try:
                self.assertEqual(embed.start(tmp + "/data", tmp + "/out")["port"], info["port"], "a second start returns the running server")
                c = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                c.request("GET", "/?token=embed-token-0123456789", headers={"Host": f"127.0.0.1:{info['port']}"})
                r = c.getresponse()
                cookie = r.getheader("Set-Cookie") or ""
                r.read()
                self.assertIn(r.status, (200, 302, 303))
                self.assertIn("slai_scical_token", cookie)
                c = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                c.request("POST", "/api/calc", body=json.dumps({"input": "6*7"}), headers={
                    "Host": f"127.0.0.1:{info['port']}", "Cookie": cookie.split(";")[0], "Content-Type": "application/json", "X-SLAI-SciCal": "1"})
                r = c.getresponse()
                body = json.loads(r.read())
                self.assertEqual(r.status, 200)
                self.assertEqual(body["value"]["text"], "42")
                self.assertEqual(body["value"]["text"], "42")
            finally:
                embed.stop()
            embed.stop()                                                     # twice is harmless
            with self.assertRaises(OSError):
                http.client.HTTPConnection("127.0.0.1", info["port"], timeout=2).request("GET", "/")


ROOT = Path(__file__).resolve().parent.parent


class DesktopLauncherProtocol(unittest.TestCase):
    """What the Tauri shell relies on: one READY line with the address, a fallback port, and exit when the shell's pipe closes."""

    def start(self, tmp: str, *extra: str) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--agents", "none", "--ready-line", "--exit-on-stdin-close", "--port-fallback",
                                 "--data-dir", tmp + "/data", "--output-dir", tmp + "/out", "--workers", "1", *extra],
                                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])})

    @staticmethod
    def ready(proc: subprocess.Popen) -> dict:
        deadline = time.time() + 60
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("SCICAL_READY "):
                return json.loads(line[len("SCICAL_READY "):])
        raise AssertionError("no SCICAL_READY line")

    def test_ready_line_gives_a_working_address_and_closing_stdin_stops_the_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.start(tmp, "--port", "0")
            try:
                info = self.ready(proc)
                self.assertTrue(info["url"].startswith(f"http://127.0.0.1:{info['port']}/?token="))
                self.assertEqual(len(info["token"]) >= 16, True)
                c = http.client.HTTPConnection("127.0.0.1", info["port"], timeout=10)
                c.request("GET", "/?token=" + info["token"], headers={"Host": f"127.0.0.1:{info['port']}"})
                self.assertIn(c.getresponse().status, (200, 302, 303))
                proc.stdin.close()
                self.assertEqual(proc.wait(timeout=20), 0, "the engine ended by itself when its input closed")
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.stdout.close()

    def test_a_taken_port_falls_back_to_a_free_one(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            proc = self.start(tmp, "--port", str(taken.getsockname()[1]))
            try:
                info = self.ready(proc)
                self.assertNotEqual(info["port"], taken.getsockname()[1])
            finally:
                proc.stdin.close()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
