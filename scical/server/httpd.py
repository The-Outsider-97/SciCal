"""The local web server. It listens on the loopback interface only and treats every request as untrusted.

* **Who may ask**: a random token, shown only in the link printed at start-up, is exchanged for an HttpOnly, SameSite=Strict cookie.
  Every other request needs that cookie. Another program on this computer or a web page open in the browser cannot read the token.
* **Which page may ask**: the ``Host`` header must be this server (defeats DNS rebinding); changes (POST/PUT/PATCH/DELETE) also need the
  ``X-SLAI-SciCal`` header and, when the browser sends an ``Origin``, that origin must be this server.
* **What the page may do**: a strict Content-Security-Policy (own scripts and styles only, no inline script, no plugins, no framing).
* **What it may be sent**: request bodies are read only up to a per-route limit; JSON is parsed, never evaluated.
"""
from __future__ import annotations

import hmac
import http.cookies
import json
import mimetypes
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from ..errors import BadRequest, NotFound, SciCalError, Unauthorized
from . import api  # noqa: F401  (registers the routes)
from .app import SciCalApp
from .router import Request, Response, router

COOKIE = "slai_scical_token"
MARKER = "x-slai-scical"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin", "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}
LOCKED_PAGE = (b"<!doctype html><meta charset=utf-8><title>SLAI SciCal</title><body style=\"font:16px system-ui;margin:3rem\">"
               b"<h1>SLAI SciCal</h1><p>This page needs the link that SciCal printed when it started (it contains a one-time access token). "
               b"Open that link, or start SciCal again.</p></body>")
ASSET = re.compile(r"^(?:icons/)?[A-Za-z0-9][A-Za-z0-9 _.-]{0,80}\.(?:png|svg|ico|jpg|jpeg|webp)$")
MIME_FIX = {".js": "text/javascript", ".mjs": "text/javascript", ".svg": "image/svg+xml", ".json": "application/json", ".css": "text/css"}


class SciCalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app: SciCalApp, client_dir: Path) -> None:
        self.app = app
        self.client_dir = client_dir.resolve()
        super().__init__((app.settings.host, app.settings.port), Handler)
        self.port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"}

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class Handler(BaseHTTPRequestHandler):
    server: SciCalHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "SLAISciCal"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:       # quiet: what a person calculates does not belong in a log
        return

    # ------------------------------------------------------------------ plumbing
    def _send(self, resp: Response) -> None:
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        if resp.download_name:
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", resp.download_name)
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(resp.body)))
        if "Cache-Control" not in resp.headers:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    @staticmethod
    def _error(exc: SciCalError) -> Response:
        return Response(exc.status, json.dumps({"ok": False, "error": exc.to_dict()}, ensure_ascii=False).encode("utf-8"))

    def _authorised(self) -> bool:
        raw = self.headers.get("Cookie")
        if not raw:
            return False
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            return False
        morsel = jar.get(COOKIE)
        return morsel is not None and hmac.compare_digest(morsel.value.encode(), self.server.app.settings.token.encode())

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "").lower() in self.server.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin.lower() in {f"http://{h}" for h in self.server.allowed_hosts}

    # ------------------------------------------------------------------ dispatch
    def _handle(self) -> None:
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        try:
            if not self._host_ok():
                return self._send(self._error(Unauthorized("This address is not allowed")))
            if path == "/" and "token" in query:                  # token exchange: /?token=...  ->  cookie, then a clean URL
                if hmac.compare_digest(query["token"].encode(), self.server.app.settings.token.encode()):
                    cookie = f"{COOKIE}={self.server.app.settings.token}; Path=/; HttpOnly; SameSite=Strict"
                    return self._send(Response(302, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie}))
                return self._send(Response(403, LOCKED_PAGE, "text/html; charset=utf-8"))
            if not self._authorised():
                if path.startswith("/api/"):
                    return self._send(self._error(Unauthorized("Not signed in. Open SciCal from the link it printed at start-up.")))
                return self._send(Response(403, LOCKED_PAGE, "text/html; charset=utf-8"))
            if path.startswith("/api/"):
                return self._send(self._api(path, query))
            if self.command not in ("GET", "HEAD"):
                return self._send(self._error(BadRequest("Method not allowed")))
            if path.startswith("/assets/"):
                return self._send(self._asset(path[len("/assets/"):]))
            return self._send(self._static(path))
        except SciCalError as exc:
            self._send(self._error(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 - the person gets a plain message; the trace goes to the console
            traceback.print_exc(file=sys.stderr)
            try:
                self._send(self._error(SciCalError("Something went wrong inside SciCal. The details are in its console window.")))
            except Exception:  # noqa: BLE001
                pass

    def _api(self, path: str, query: dict[str, str]) -> Response:
        mutating = self.command in ("POST", "PUT", "PATCH", "DELETE")
        if mutating:
            if MARKER not in {k.lower() for k in self.headers.keys()}:
                raise Unauthorized("Missing request marker")
            if not self._origin_ok():
                raise Unauthorized("Cross-origin requests are not allowed")
        found = router.match(self.command if self.command != "HEAD" else "GET", path)
        if found is None:
            raise NotFound("There is no such function")
        if found == "method":
            raise BadRequest("Method not allowed for this address")
        handler, params = found                                       # type: ignore[misc]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise BadRequest("Bad Content-Length") from exc
        if length < 0:
            raise BadRequest("Bad Content-Length")
        req = Request(self.command, path, query, {k.lower(): v for k, v in self.headers.items()}, self.rfile, length or None, params)
        out = handler(self.server.app, req)
        if mutating and not req._read and length:
            self.close_connection = True                              # an unread body would corrupt the next request on this connection
        return out

    def _file(self, root: Path, rel: str, cache: str) -> Response:
        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise NotFound("Not found") from None
        if not target.is_file():
            raise NotFound("Not found")
        mime = MIME_FIX.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/json",):
            mime += "; charset=utf-8"
        return Response(200, target.read_bytes(), mime, {"Cache-Control": cache})

    def _static(self, path: str) -> Response:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        return self._file(self.server.client_dir, rel, "no-cache")

    def _asset(self, rel: str) -> Response:
        """Icons live once, in the SLAI-wide ``applications/assets`` folder; they are served from there and never copied into the app."""
        if not ASSET.match(rel):
            raise NotFound("Not found")
        return self._file(self.server.app.settings.assets_dir, rel, "public, max-age=3600")

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

    def do_OPTIONS(self) -> None:       # no cross-origin pre-flight is ever approved
        self._send(Response(405, b"", "text/plain"))
