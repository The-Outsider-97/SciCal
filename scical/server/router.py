"""A small router and the request/response types of the HTTP layer (kept apart from the server so handlers are testable)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable

from ..errors import BadRequest, LimitExceeded

MAX_JSON_BYTES = 8 * 1024 * 1024


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    stream: BinaryIO | None = None
    length: int | None = None
    params: dict[str, str] = field(default_factory=dict)
    _json: Any = None
    _read: bool = False

    def json(self, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
        if not self._read:
            self._read = True
            if self.stream is None or not self.length:
                self._json = {}
            else:
                if self.length > min(limit, MAX_JSON_BYTES):
                    raise LimitExceeded("The request is too large")
                raw = self.stream.read(self.length)
                try:
                    self._json = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                    raise BadRequest(f"The request is not valid JSON: {exc}") from exc
        if not isinstance(self._json, dict):
            raise BadRequest("The request body must be a JSON object")
        return self._json

    def int_query(self, name: str, default: int, low: int, high: int) -> int:
        raw = self.query.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise BadRequest(f"'{name}' must be a whole number") from exc
        return max(low, min(high, value))


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    download_name: str | None = None


Handler = Callable[[Any, Request], Any]


class Router:
    def __init__(self) -> None:
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, regex, handler))

    def route(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.add(method, pattern, fn)
            return fn
        return deco

    def match(self, method: str, path: str) -> tuple[Handler, dict[str, str]] | None | str:
        allowed = False
        for m, regex, handler in self.routes:
            found = regex.match(path)
            if found:
                if m == method:
                    return handler, found.groupdict()
                allowed = True
        return "method" if allowed else None


router = Router()
route = router.route


def ok(data: Any = None, **extra: Any) -> Response:
    payload = {"ok": True, "data": data}
    payload.update(extra)
    return Response(200, json.dumps(payload, default=str, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def file_response(body: bytes, name: str, content_type: str) -> Response:
    return Response(200, body, content_type, {"Cache-Control": "no-store"}, download_name=name)
