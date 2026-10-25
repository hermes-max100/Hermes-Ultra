"""HTTP API, live change stream and static UI for the Lane Command Center.

Standard library only. Binds to loopback by default; binding anywhere else
requires an access token. Mutating requests must be JSON, and cross-origin
requests are rejected, so a web page in the operator's browser cannot drive the
API behind their back.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .council import Council
from .store import CommandCenterStore, Conflict, NotFound, StoreError

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}

Handler = Callable[["RequestContext"], Any]


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class RequestContext:
    def __init__(self, handler: "CommandCenterHandler", params: dict[str, str], query: dict[str, list[str]],
                 raw_body: bytes = b"") -> None:
        self.handler = handler
        self.params = params
        self.query = query
        self._raw = raw_body
        self._body: Any = None

    @property
    def app(self) -> "CommandCenterApp":
        return self.handler.server.app  # type: ignore[attr-defined]

    def arg(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default

    def json(self) -> dict[str, Any]:
        if self._body is None:
            try:
                body = json.loads(self._raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HttpError(400, f"invalid JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise HttpError(400, "JSON body must be an object")
            self._body = body
        return self._body

    @property
    def actor(self) -> str:
        return str(self.handler.headers.get("X-CC-Actor") or "operator")[:80]


def _host_only(header: str) -> str:
    if header.startswith("["):
        return header.split("]")[0] + "]"
    return header.rsplit(":", 1)[0]


def _is_loopback_host(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class CommandCenterApp:
    def __init__(self, store: CommandCenterStore, council: Council, *, token: str | None = None) -> None:
        self.store = store
        self.council = council
        self.token = token or None
        self.stopping = threading.Event()
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self._register()

    def route(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")
        self.routes.append((method, regex, handler))

    def _register(self) -> None:
        r = self.route
        r("GET", "/api/state", lambda c: self.state())
        r("GET", "/api/lanes", lambda c: self.store.list_lanes())
        r("POST", "/api/lanes", lambda c: self.store.create_lane(
            c.json().get("id"), name=c.json().get("name"), ownership=c.json().get("ownership", "owned"),
            kind=c.json().get("kind", "production"), status=c.json().get("status", "idle"),
            description=c.json().get("description", ""), actor=c.actor))
        r("PATCH", "/api/lanes/{lane}", lambda c: self.store.update_lane(c.params["lane"], c.json(), actor=c.actor))
        r("GET", "/api/lanes/{lane}/messages", lambda c: self.store.lane_messages(
            c.params["lane"], limit=int(c.arg("limit", "100")), before_id=int(c.arg("before", "0")) or None,
            work_type=c.arg("work_type") or None))
        r("POST", "/api/lanes/{lane}/messages", lambda c: self.store.post_lane_message(
            c.params["lane"], author=c.json().get("author") or c.actor, title=c.json().get("title"),
            work_type=c.json().get("work_type", "other"), body=c.json().get("body", ""), model=c.json().get("model"),
            tokens_in=c.json().get("tokens_in"), tokens_out=c.json().get("tokens_out"),
            cost_usd=c.json().get("cost_usd"), latency_ms=c.json().get("latency_ms"), task_id=c.json().get("task_id")))
        r("GET", "/api/messages/{message}", lambda c: self.store.get_lane_message(int(c.params["message"])))

        r("GET", "/api/council/members", lambda c: self.council.roster())
        r("POST", "/api/council/members", lambda c: self.store.add_member(
            c.json().get("id"), display_name=c.json().get("display_name"), provider=c.json().get("provider"),
            model=c.json().get("model"), base_url=c.json().get("base_url"), credential_env=c.json().get("credential_env"),
            seat=c.json().get("seat", "bench"), home_lane_id=c.json().get("home_lane_id"), effort=c.json().get("effort"),
            price_in_per_m=c.json().get("price_in_per_m"), price_out_per_m=c.json().get("price_out_per_m"), actor=c.actor))
        r("PATCH", "/api/council/members/{member}", lambda c: self.store.update_member(c.params["member"], c.json(), actor=c.actor))
        r("POST", "/api/council/members/{member}/promote", lambda c: self.store.promote(c.params["member"], actor=c.actor))
        r("POST", "/api/council/members/{member}/demote", lambda c: self.store.demote(c.params["member"], actor=c.actor))
        r("POST", "/api/council/reorder", lambda c: self.store.reorder(
            c.json().get("seat", "council"), c.json().get("order") or [], actor=c.actor))
        r("GET", "/api/council/messages", lambda c: self.store.council_messages(
            limit=int(c.arg("limit", "200")), after_id=int(c.arg("after", "0")) or None))
        r("POST", "/api/council/messages", self._council_post)

        r("GET", "/api/tasks", lambda c: self.store.list_tasks(lane_id=c.arg("lane") or None, state=c.arg("state") or None))
        r("POST", "/api/tasks", lambda c: self.store.create_task(
            c.json().get("lane_id"), title=c.json().get("title"), detail=c.json().get("detail", ""),
            state=c.json().get("state", "backlog"), priority=c.json().get("priority", 3),
            assignee=c.json().get("assignee"), task_id=c.json().get("id"), actor=c.actor))
        r("GET", "/api/tasks/{task}", lambda c: self.store.task_detail(c.params["task"]))
        r("POST", "/api/tasks/{task}/transition", lambda c: self.store.transition_task(
            c.params["task"], c.json().get("to"), actor=c.actor, note=c.json().get("note", ""),
            blocker=c.json().get("blocker"), evidence=c.json().get("evidence"), progress=c.json().get("progress")))
        r("POST", "/api/tasks/{task}/progress", lambda c: self.store.update_task_progress(
            c.params["task"], c.json().get("progress"), actor=c.actor))

        r("GET", "/api/experiments", lambda c: self.store.list_experiments(lane_id=c.arg("lane") or None))
        r("POST", "/api/experiments", lambda c: self.store.create_experiment(
            c.json().get("lane_id"), title=c.json().get("title"), kind=c.json().get("kind", "hypothesis"),
            hypothesis=c.json().get("hypothesis", ""), status=c.json().get("status", "planned"),
            metrics=c.json().get("metrics"), experiment_id=c.json().get("id"), actor=c.actor))
        r("GET", "/api/experiments/{experiment}", lambda c: self.store.experiment_detail(c.params["experiment"]))
        r("PATCH", "/api/experiments/{experiment}", lambda c: self.store.update_experiment(
            c.params["experiment"], status=c.json().get("status"), result_summary=c.json().get("result_summary"),
            metrics=c.json().get("metrics"), actor=c.actor))
        r("POST", "/api/experiments/{experiment}/events", lambda c: self.store.log_experiment(
            c.params["experiment"], c.json().get("message"), level=c.json().get("level", "info"), actor=c.actor))

        r("GET", "/api/activity", lambda c: self.store.activity(
            after_seq=int(c.arg("after", "0")), limit=int(c.arg("limit", "200"))))

    def _council_post(self, c: RequestContext) -> Any:
        body = c.json()
        if body.get("speaker_kind") == "model":
            # External or manual seats post their own replies.
            member = self.store.get_member(body.get("speaker_id"))
            if member["seat"] != "council" and member["provider"] != "manual":
                raise HttpError(409, f"{member['id']} is not seated on the council")
            return self.store.post_council_message(
                round_id=body.get("round_id") or "external", speaker_kind="model", speaker_id=member["id"],
                body=body.get("body"), model=body.get("model") or member["model"])
        result = self.council.submit(body.get("body"), speaker_id=c.actor, mode=body.get("mode") or "lead")
        return result, HTTPStatus.ACCEPTED

    def state(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "summary": self.store.summary(),
            "lanes": self.store.list_lanes(),
            "council": self.council.roster(),
            "active_rounds": self.council.active_rounds(),
            "auth": bool(self.token),
        }

    def check_token(self, presented: str | None) -> bool:
        if not self.token:
            return True
        return bool(presented) and hmac.compare_digest(presented.encode(), self.token.encode())


class CommandCenterHandler(BaseHTTPRequestHandler):
    server_version = "HermesCommandCenter"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default; uvicorn-style access logs not needed
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    @property
    def app(self) -> CommandCenterApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, method: str, query: dict[str, list[str]], path: str) -> None:
        host = _host_only(self.headers.get("Host") or "")
        if not self.app.token and not _is_loopback_host(host):
            raise HttpError(403, "host not allowed without an access token")
        origin = self.headers.get("Origin")
        if origin:
            origin_host = urlsplit(origin).netloc
            # A TLS proxy such as `tailscale serve` may rewrite Host but forwards the original.
            if origin_host not in {self.headers.get("Host") or "", self.headers.get("X-Forwarded-Host") or ""}:
                raise HttpError(403, "cross-origin requests are not allowed")
        if method in ("POST", "PATCH"):
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type != "application/json":
                raise HttpError(415, "mutating requests must send Content-Type: application/json")
        if path.startswith("/api/"):
            presented = self.headers.get("X-CC-Token")
            auth = self.headers.get("Authorization") or ""
            if not presented and auth.lower().startswith("bearer "):
                presented = auth[7:].strip()
            if not presented and path == "/api/stream":
                presented = (query.get("token") or [None])[0]
            if not self.app.check_token(presented):
                raise HttpError(401, "missing or invalid access token")

    def _dispatch(self, method: str) -> None:
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        try:
            # Always consume the body so a keep-alive connection never reads it as the next request line.
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self.close_connection = True
                raise HttpError(413 if length > MAX_BODY else 400, "invalid or oversized request body")
            raw_body = self.rfile.read(length) if length else b""
            self._guard(method, query, path)
            if method == "GET" and not path.startswith("/api/"):
                return self._static(path)
            if method == "GET" and path == "/api/stream":
                return self._stream(query)
            for route_method, regex, handler in self.app.routes:
                match = regex.match(path)
                if match and route_method == method:
                    result = handler(RequestContext(self, match.groupdict(), query, raw_body))
                    status = HTTPStatus.OK
                    if isinstance(result, tuple):
                        result, status = result
                    elif method == "POST":
                        status = HTTPStatus.CREATED
                    return self._send_json(int(status), result)
            raise HttpError(404, f"no route for {method} {path}")
        except HttpError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except NotFound as exc:
            self._send_json(404, {"error": str(exc)})
        except Conflict as exc:
            self._send_json(409, {"error": str(exc)})
        except (StoreError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if STATIC_DIR not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
            raise HttpError(404, "not found")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[target.suffix])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, query: dict[str, list[str]]) -> None:
        after = int((query.get("after") or ["0"])[0] or 0)
        last_event = self.headers.get("Last-Event-ID")
        if last_event and last_event.isdigit():
            after = max(after, int(last_event))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        heartbeat = time.monotonic()
        poll = getattr(self.server, "stream_poll", 0.5)
        while not self.app.stopping.is_set():
            rows = self.app.store.activity(after_seq=after, limit=200)
            for row in rows:
                after = row["seq"]
                chunk = f"id: {row['seq']}\nevent: activity\ndata: {json.dumps(row, default=str)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
            if rows:
                self.wfile.flush()
                heartbeat = time.monotonic()
            elif time.monotonic() - heartbeat > 15:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                heartbeat = time.monotonic()
            self.app.stopping.wait(poll)


class CommandCenterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: CommandCenterApp, *, verbose: bool = False,
                 stream_poll: float = 0.5) -> None:
        if not app.token and not _is_loopback_host(address[0]):
            raise ValueError(
                f"refusing to bind {address[0]} without an access token; set HERMES_CC_TOKEN or bind 127.0.0.1"
            )
        self.app = app
        self.verbose = verbose
        self.stream_poll = stream_poll
        super().__init__(address, CommandCenterHandler)

    def shutdown(self) -> None:
        self.app.stopping.set()
        super().shutdown()
