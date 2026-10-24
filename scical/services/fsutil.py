"""Writing files so that a crash or a full disk never leaves half a file behind, and so that odd Windows set-ups still work.

The normal route is: write a temporary file next to the target, flush it to disk, then rename it over the target in one step.
On some Windows machines that rename fails even inside one folder (``WinError 17`` "cannot move to another drive" in a redirected
or virtualised AppData folder, or ``WinError 5``/``32`` while an antivirus scanner holds the new file). Those are retried a few times,
and as a last resort the data is written straight into the target, so the person's work is saved either way.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_RETRIES = 5


def atomic_write(path: Path | str, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        last: OSError | None = None
        for attempt in range(_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except OSError as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        # The rename will not work here. Write in place instead (not atomic, but nothing is lost).
        try:
            with open(path, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
        except OSError:
            if last is not None:
                raise last
            raise
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def atomic_write_text(path: Path | str, text: str) -> None:
    atomic_write(path, text.encode("utf-8"))
