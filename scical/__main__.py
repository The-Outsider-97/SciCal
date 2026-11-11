"""``python -m scical`` - start SLAI SciCal."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    from .server.config import Settings
    p = argparse.ArgumentParser(prog="python -m scical", description="SLAI SciCal - a scientific calculator and STEM workbench on your own computer")
    p.add_argument("--host", default="127.0.0.1", help="address to listen on (loopback only)")
    p.add_argument("--port", type=int, default=8768)
    p.add_argument("--slai-root", help="path to the SLAI checkout (default: found automatically)")
    p.add_argument("--data-dir", help="where SciCal keeps worksheets and preferences")
    p.add_argument("--output-dir", help="where exports are written")
    p.add_argument("--assets-dir", help="folder with the SLAI-wide icons (default: applications/assets)")
    p.add_argument("--agents", choices=("auto", "none", "strict"), default=None, help="optional SLAI assistant: auto (default), none (never use agents), strict")
    p.add_argument("--workers", type=int, default=0, help="number of calculation worker processes (default: up to 4)")
    p.add_argument("--timeout", type=float, default=None, help="seconds a single calculation may run (default 30)")
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    p.add_argument("--token", help="fixed access token (for tests; random by default)")
    p.add_argument("--client-dir", help="folder with the built web client")
    p.add_argument("--worker-mode", choices=("auto", "process", "thread"), default=None, help="run calculations in worker processes, in threads (iOS, Android) or choose automatically")
    p.add_argument("--port-fallback", action="store_true", help="if --port is taken, listen on any free port instead")
    p.add_argument("--ready-line", action="store_true", help="print one machine-readable line, SCICAL_READY {json}, when the server is listening (used by the desktop app)")
    p.add_argument("--exit-on-stdin-close", action="store_true", help="stop when standard input closes, so the engine ends with the app that started it")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = p.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("Refusing to listen on a non-loopback address: SciCal is a local app and holds your worksheets.", file=sys.stderr)
        return 2
    s = Settings(host=args.host, port=args.port)
    if args.data_dir:
        s.data_dir = Path(args.data_dir).expanduser().resolve()
    if args.output_dir:
        s.output_dir = Path(args.output_dir).expanduser().resolve()
    if args.assets_dir:
        s.assets_dir = Path(args.assets_dir).expanduser().resolve()
    if args.token:
        s.token = args.token
    if args.agents:
        s.agents = args.agents
    if args.slai_root or os.environ.get("SLAI_ROOT"):
        s.slai_root = Path(args.slai_root or os.environ["SLAI_ROOT"]).expanduser().resolve()
    if args.workers:
        s.workers = max(1, min(16, args.workers))
    if args.timeout:
        s.task_timeout_s = max(1.0, min(600.0, args.timeout))
    if args.worker_mode:
        s.worker_mode = args.worker_mode
    s.open_browser = not args.no_browser

    if args.client_dir:
        client = Path(args.client_dir).expanduser().resolve()
    elif getattr(sys, "frozen", False):                       # the frozen desktop engine keeps the web client in a folder beside it
        client = Path(sys.executable).resolve().parent / "client"
    else:
        client = Path(__file__).resolve().parent.parent / "dist"
    from .server.config import assets_for
    s.assets_dir = assets_for(s.assets_dir, client)
    if not (client / "index.html").is_file():
        print(f"The web client was not found in {client}. Run 'npm install && npm run build' in the SciCal folder.", file=sys.stderr)
        return 2
    from .server.app import SciCalApp
    from .server.httpd import SciCalHTTPServer
    app = SciCalApp(s)
    try:
        server = SciCalHTTPServer(app, client)
    except OSError as exc:
        server = None
        if args.port_fallback and s.port != 0:
            s.port = 0
            try:
                server = SciCalHTTPServer(app, client)
            except OSError as exc2:
                exc = exc2
        if server is None:
            print(f"Cannot listen on {s.host}:{s.port}: {exc}. Try --port.", file=sys.stderr)
            app.close()
            return 2
    url = f"{server.base_url}/?token={s.token}"
    print(f"{APP_NAME} {__version__}\n  SLAI root : {s.slai_root or 'not found (SLDC export unavailable)'}\n  Data      : {s.data_dir}\n  Exports   : {s.output_dir}\n"
          f"  Icons     : {s.assets_dir}\n  Open      : {url}", flush=True)
    for note in app.startup_notes:
        print(f"  notice    : {note}", flush=True)
    if args.ready_line:
        import json
        print("SCICAL_READY " + json.dumps({"port": server.port, "token": s.token, "url": url, "version": __version__}), flush=True)
    if s.open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    import signal

    def stop(*_: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), stop)
            except (ValueError, OSError):
                pass
    if args.exit_on_stdin_close:
        def watch_parent() -> None:
            try:
                while sys.stdin.buffer.read(4096):
                    pass
            except Exception:  # noqa: BLE001
                pass
            stop()
        threading.Thread(target=watch_parent, name="scical-parent-watch", daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()          # a frozen (PyInstaller) build starts its calculation workers through this
    raise SystemExit(main())
