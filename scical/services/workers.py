"""A small pool of long-lived worker processes.

Why processes: a symbolic integral or a huge exact power can run for minutes and cannot be interrupted from inside Python. Each
task runs in a worker; if it takes longer than its limit, or the person cancels it, the worker is killed and replaced and the
caller gets a clear 'timed out' / 'cancelled' error. A worker also restarts after a number of tasks to keep memory flat.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import sys
import threading
import time
from typing import Any

from ..errors import Busy, Cancelled, SciCalError, TimedOut

RECYCLE_AFTER = 400
MEMORY_LIMIT_BYTES = 3 * 1024 ** 3


def _worker_main(conn: Any) -> None:
    """Runs in the child process: receive a task, run it, send the result."""
    try:
        import resource                                              # POSIX only
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except Exception:  # noqa: BLE001 - not available on Windows; the timeout still protects the server
        pass
    from . import tasks
    try:
        tasks.run({"kind": "ping"})
        import sympy  # noqa: F401  (warm the heavy imports before the first real task)
    except Exception:  # noqa: BLE001
        pass
    conn.send(("ready", None))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        job_id, task = msg
        try:
            out = tasks.run(task)
        except SciCalError as exc:
            out = {"ok": False, "error": exc.to_dict()}
        except BaseException as exc:  # noqa: BLE001 - never let a bug kill the loop silently
            out = {"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {str(exc)[:200]}"}}
        try:
            conn.send((job_id, out))
        except (BrokenPipeError, OSError):
            return


class Worker:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker_main, args=(child,), daemon=True)
        self.proc.start()
        child.close()
        self.tasks_done = 0
        self.ready = False
        self.job: str | None = None

    def wait_ready(self, timeout: float) -> bool:
        if self.ready:
            return True
        if self.parent.poll(timeout):
            try:
                self.parent.recv()
                self.ready = True
            except (EOFError, OSError):
                return False
        return self.ready

    def kill(self) -> None:
        try:
            self.proc.terminate()
            self.proc.join(1.0)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(1.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.parent.close()
        except Exception:  # noqa: BLE001
            pass


class Pool:
    def __init__(self, size: int | None = None, default_timeout: float = 30.0, queue_wait: float = 20.0) -> None:
        self.size = max(1, size or min(4, os.cpu_count() or 2))
        self.default_timeout = default_timeout
        self.queue_wait = queue_wait
        self.ctx = mp.get_context("spawn")
        self.idle: "queue.Queue[Worker]" = queue.Queue()
        self.lock = threading.Lock()
        self.busy: dict[str, Worker] = {}
        self.cancelled: set[str] = set()
        self.closed = False
        self.start_failures = 0
        self.stats = {"tasks": 0, "timeouts": 0, "cancelled": 0, "restarts": 0}
        self._spawn_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "Pool":
        """Start the workers in the background so the first request does not pay for importing SymPy."""
        def go() -> None:
            for _ in range(self.size):
                if self.closed:
                    return
                self.idle.put(Worker(self.ctx))
        self._spawn_thread = threading.Thread(target=go, name="scical-pool-start", daemon=True)
        self._spawn_thread.start()
        return self

    def close(self) -> None:
        self.closed = True
        while True:
            try:
                self.idle.get_nowait().kill()
            except queue.Empty:
                break
        with self.lock:
            for w in list(self.busy.values()):
                w.kill()

    def status(self) -> dict[str, Any]:
        return {"size": self.size, "idle": self.idle.qsize(), "busy": len(self.busy), **self.stats, "defaultTimeoutS": self.default_timeout}

    # ------------------------------------------------------------------ running
    def _acquire(self) -> Worker:
        deadline = time.monotonic() + self.queue_wait
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self.closed:
                raise Busy("SciCal is busy with other calculations. Try again in a moment.")
            try:
                w = self.idle.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if not w.proc.is_alive():
                w.kill()
                self.stats["restarts"] += 1
                w = Worker(self.ctx)
            if not w.wait_ready(60):
                w.kill()
                self.stats["restarts"] += 1
                self.start_failures += 1
                if self.start_failures >= 3:
                    self.closed = True
                    raise Busy("The calculation workers could not start. Check that SciCal's Python packages are installed (see the console).")
                self.idle.put(Worker(self.ctx))
                continue
            self.start_failures = 0
            return w

    def _replace(self) -> None:
        if not self.closed:
            self.stats["restarts"] += 1
            threading.Thread(target=lambda: self.idle.put(Worker(self.ctx)), daemon=True).start()

    def submit(self, task: dict[str, Any], job_id: str, timeout: float | None = None) -> dict[str, Any]:
        timeout = timeout or self.default_timeout
        w = self._acquire()
        with self.lock:
            w.job = job_id
            self.busy[job_id] = w
        self.stats["tasks"] += 1
        try:
            try:
                w.parent.send((job_id, task))
            except (BrokenPipeError, OSError):
                w.kill()
                self._replace()
                raise Busy("A worker stopped unexpectedly. Please try again.") from None
            end = time.monotonic() + timeout
            while True:
                if job_id in self.cancelled:
                    self.cancelled.discard(job_id)
                    w.kill()
                    self._replace()
                    self.stats["cancelled"] += 1
                    raise Cancelled("The calculation was cancelled")
                left = end - time.monotonic()
                if left <= 0:
                    w.kill()
                    self._replace()
                    self.stats["timeouts"] += 1
                    raise TimedOut(f"The calculation took longer than {timeout:g} seconds and was stopped",
                                   hint="Try a simpler input, fewer digits, or a smaller range.")
                try:
                    if w.parent.poll(min(left, 0.1)):
                        got_id, result = w.parent.recv()
                        break
                except (EOFError, OSError):
                    w.kill()
                    self._replace()
                    if job_id in self.cancelled:
                        self.cancelled.discard(job_id)
                        raise Cancelled("The calculation was cancelled") from None
                    raise Busy("The calculation stopped unexpectedly (it may have run out of memory).") from None
            w.tasks_done += 1
            if w.tasks_done >= RECYCLE_AFTER:
                w.kill()
                self._replace()
            else:
                self.idle.put(w)
            return result
        finally:
            with self.lock:
                self.busy.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            if job_id in self.busy:
                self.cancelled.add(job_id)
                return True
        return False
