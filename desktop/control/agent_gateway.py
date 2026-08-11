#!/usr/bin/env python3
"""Capability-gated, allowlisted streaming proxy for the Coddy browser panel."""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_UPSTREAM_BYTES = 16 * 1024 * 1024


class UpstreamLimitError(RuntimeError):
    pass


def stream_limited(upstream: http.client.HTTPResponse, destination: object) -> None:
    total = 0
    while chunk := upstream.read1(16 * 1024):
        total += len(chunk)
        if total > MAX_UPSTREAM_BYTES:
            raise UpstreamLimitError("Coddy response exceeded 16 MiB")
        destination.write(chunk)  # type: ignore[attr-defined]
        destination.flush()  # type: ignore[attr-defined]


class RoutePolicy:
    SESSION = r"sess_[0-9a-f]{16,64}"
    SESSION_VALUE = re.compile(rf"^{SESSION}$")
    ROUTES = (
        ("GET", re.compile(r"^/v1/models$")),
        ("POST", re.compile(r"^/v1/responses$")),
        ("GET", re.compile(r"^/coddy/sessions$")),
        ("GET", re.compile(rf"^/coddy/sessions/{SESSION}/messages$")),
        ("GET", re.compile(rf"^/coddy/sessions/{SESSION}/composer-stream$")),
        ("POST", re.compile(rf"^/coddy/sessions/{SESSION}/permission$")),
        ("POST", re.compile(rf"^/coddy/sessions/{SESSION}/cancel$")),
    )
    SESSION_PATH = re.compile(rf"^/coddy/sessions/({SESSION})/")

    @classmethod
    def allowed(cls, method: str, path: str) -> bool:
        return any(method == expected and pattern.fullmatch(path) for expected, pattern in cls.ROUTES)

    @classmethod
    def session_matches(cls, path: str, header: str) -> bool:
        match = cls.SESSION_PATH.match(path)
        if path == "/v1/responses" or match is not None:
            return bool(
                cls.SESSION_VALUE.fullmatch(header)
                and (match is None or hmac.compare_digest(match.group(1), header))
            )
        return not header or cls.SESSION_VALUE.fullmatch(header) is not None


class AgentGatewayHandler(BaseHTTPRequestHandler):
    server_version = "RelayAgentGateway/1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")

    def _proxy(self, method: str) -> None:
        path = urlsplit(self.path).path
        if not self._human_authorized():
            self._json_error(403, "HUMAN_AUTH_REQUIRED", "valid human capability required")
            return
        if not RoutePolicy.allowed(method, path):
            self._json_error(404, "NOT_FOUND", "agent route not found")
            return
        session_header = self.headers.get("X-Coddy-Session-ID", "")
        if not RoutePolicy.session_matches(path, session_header):
            self._json_error(422, "SESSION_MISMATCH", "session header does not match route")
            return

        body = None
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json_error(400, "BAD_REQUEST", "invalid content length")
                return
            if not 0 < length <= 256 * 1024:
                self._json_error(413, "PAYLOAD_TOO_LARGE", "body limit is 256 KiB")
                return
            body = self.rfile.read(length)

        try:
            upstream_connection, upstream = self._upstream(method, path, body, session_header)
        except (OSError, http.client.HTTPException):
            self._json_error(502, "AGENT_UNAVAILABLE", "Coddy agent is unavailable")
            return

        self.send_response(upstream.status)
        content_type = upstream.getheader("Content-Type", "application/json")
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if value := upstream.getheader("X-Coddy-Session-ID"):
            self.send_header("X-Coddy-Session-ID", value)
        if value := upstream.getheader("Content-Length"):
            self.send_header("Content-Length", value)
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        try:
            stream_limited(upstream, self.wfile)
        except UpstreamLimitError:
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()
            upstream_connection.close()

    def _upstream(
        self, method: str, path: str, body: bytes | None, session_header: str
    ) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
        target = urlsplit(self.server.coddy_base_url)  # type: ignore[attr-defined]
        connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(target.hostname, target.port, timeout=920)
        headers = {
            "Authorization": f"Bearer {self.server.coddy_token}",  # type: ignore[attr-defined]
            "Accept": "text/event-stream, application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if session_header:
            headers["X-Coddy-Session-ID"] = session_header
        connection.request(method, path, body=body, headers=headers)
        return connection, connection.getresponse()

    def _human_authorized(self) -> bool:
        supplied = self.headers.get("X-Human-Control-Token", "")
        expected = self.server.human_token  # type: ignore[attr-defined]
        return isinstance(supplied, str) and hmac.compare_digest(supplied, expected)

    def _json_error(self, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, message: str, *args: object) -> None:
        print(f"agent-gateway: {message % args}", flush=True)


class AgentGatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def get_request(self):  # type: ignore[no-untyped-def]
        connection, address = super().get_request()
        connection.settimeout(30)
        return connection, address

    def __init__(
        self,
        address: tuple[str, int],
        *,
        coddy_base_url: str,
        coddy_token: str,
        human_token: str,
    ) -> None:
        target = urlsplit(coddy_base_url)
        if target.scheme not in {"http", "https"} or not target.hostname or target.path not in {"", "/"}:
            raise ValueError("CODDY_BASE_URL must be an HTTP origin without a path")
        if len(coddy_token) < 16:
            raise ValueError("Coddy token must contain at least 16 characters")
        if len(human_token) < 8:
            raise ValueError("human token must contain at least 8 characters")
        self.coddy_base_url = coddy_base_url.rstrip("/")
        self.coddy_token = coddy_token
        self.human_token = human_token
        super().__init__(address, AgentGatewayHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--human-token-file", default="/run/ai-desktop/human-token")
    args = parser.parse_args()
    AgentGatewayServer(
        (args.host, args.port),
        coddy_base_url=os.environ.get("CODDY_BASE_URL", "http://coddy:12345"),
        coddy_token=os.environ["CODDY_HTTP_TOKEN"],
        human_token=Path(args.human_token_file).read_text(encoding="utf-8").strip(),
    ).serve_forever()


if __name__ == "__main__":
    main()
