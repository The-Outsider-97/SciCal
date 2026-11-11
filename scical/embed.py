"""Start SciCal inside another program: the Android and iOS apps (and anything else that already hosts a Python interpreter).

The app calls :func:`start` once, gets back the loopback address and the access token, and points its web view at ``url``. Nothing here
opens a window or a browser. Calculations run in threads (there are no worker processes on these platforms), the SLAI assistant is off,
and the server listens on the loopback interface only, exactly as ``python -m scical`` does.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_state: dict[str, Any] = {}
_lock = threading.Lock()


def start(data_dir: str, output_dir: str, token: str | None = None, port: int = 0, client_dir: str | None = None, worker_mode: str = "thread") -> dict[str, Any]:
    """Start the server in a background thread (once; later calls return the same address). Returns ``{"port", "token", "url"}``."""
    with _lock:
        if _state:
            return dict(_state["info"])
        from . import __version__
        from .server.app import SciCalApp
        from .server.config import Settings
        from .server.httpd import SciCalHTTPServer

        s = Settings(host="127.0.0.1", port=port)
        s.data_dir = Path(data_dir).expanduser().resolve()
        s.output_dir = Path(output_dir).expanduser().resolve()
        s.output_dir.mkdir(parents=True, exist_ok=True)
        s.agents = "none"
        s.worker_mode = worker_mode
        s.open_browser = False
        if token:
            s.token = token
        client = Path(client_dir).expanduser().resolve() if client_dir else Path(__file__).resolve().parent.parent / "dist"
        if not (client / "index.html").is_file():
            raise FileNotFoundError(f"The web client was not found in {client}")
        app = SciCalApp(s)
        try:
            server = SciCalHTTPServer(app, client)
        except OSError:
            if port == 0:
                app.close()
                raise
            s.port = 0                                              # the preferred port is taken: any free port will do
            server = SciCalHTTPServer(app, client)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.25), name="scical-http", daemon=True)
        thread.start()
        info = {"port": server.port, "token": s.token, "url": f"{server.base_url}/?token={s.token}", "version": __version__}
        _state.update(app=app, server=server, thread=thread, info=info)
        return dict(info)


def stop() -> None:
    """Stop the server (the app is going away). Safe to call more than once."""
    with _lock:
        if not _state:
            return
        server, app = _state["server"], _state["app"]
        _state.clear()
    try:
        server.shutdown()
        server.server_close()
    finally:
        app.close()
