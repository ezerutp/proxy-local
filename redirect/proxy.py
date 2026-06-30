from __future__ import annotations

import json
import signal
import socket
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .models import ProxyConfig, SAFE_METHODS, origin_host_port


ALLOWED_CORS_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

CORS_RESPONSE_HEADERS = {
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-allow-credentials",
    "access-control-expose-headers",
    "access-control-max-age",
}


class RedirectHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        safe_log(f"Unhandled proxy error from {client_address}:")
        safe_log(traceback.format_exc().rstrip())


def is_port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0


def serve_proxy(proxy: ProxyConfig) -> None:
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    host, port = origin_host_port(proxy.origin)
    handler = build_proxy_handler(proxy)
    server = RedirectHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_proxy_handler(proxy: ProxyConfig) -> type[BaseHTTPRequestHandler]:
    destination = urlsplit(proxy.destination)
    destination_base_path = destination.path.rstrip("/")

    class ProxyRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._safe_handle_proxy_request()

        def do_HEAD(self) -> None:
            self._safe_handle_proxy_request()

        def do_OPTIONS(self) -> None:
            self._safe_handle_proxy_request()

        def do_POST(self) -> None:
            self._safe_handle_proxy_request()

        def do_PUT(self) -> None:
            self._safe_handle_proxy_request()

        def do_PATCH(self) -> None:
            self._safe_handle_proxy_request()

        def do_DELETE(self) -> None:
            self._safe_handle_proxy_request()

        def log_message(self, format: str, *args: Any) -> None:
            safe_log(f"{self.address_string()} - {format % args}")

        def _safe_handle_proxy_request(self) -> None:
            self.close_connection = True
            try:
                if (
                    self.command.upper() == "OPTIONS"
                    and self.headers.get("Access-Control-Request-Method")
                ):
                    self._send_empty(204)
                    return
                self._handle_proxy_request()
            except BrokenPipeError:
                safe_log("Client disconnected before proxy response was sent.")
            except ConnectionResetError:
                safe_log("Client reset the proxy connection.")
            except TimeoutError as error:
                self._send_proxy_error(504, "Gateway timeout", str(error))
            except OSError as error:
                self._send_proxy_error(502, "Proxy connection error", str(error))
            except Exception as error:
                safe_log("Unexpected proxy request error:")
                safe_log(traceback.format_exc().rstrip())
                self._send_proxy_error(502, "Proxy error", str(error))

        def _handle_proxy_request(self) -> None:
            method = self.command.upper()
            if not proxy.unsafe and method not in SAFE_METHODS:
                self._read_body()
                self._send_json(
                    403,
                    {
                        "error": "Request blocked by safe mode",
                        "method": method,
                        "hint": "Use --unsafe if you really need to allow write operations",
                    },
                )
                return

            target_url = self._target_url()
            body = self._read_body()
            headers = self._forward_headers()
            request = Request(target_url, data=body, headers=headers, method=method)

            try:
                with urlopen(request, timeout=60) as response:
                    response_body = b"" if method == "HEAD" else response.read()
                    response_headers = list(response.headers.items())
                    self._send_response(response.status, response_headers, response_body)
            except HTTPError as error:
                response_body = b"" if method == "HEAD" else error.read()
                response_headers = list(error.headers.items())
                self._send_response(error.code, response_headers, response_body)
            except URLError as error:
                self._send_json(
                    502,
                    {
                        "error": "Bad gateway",
                        "detail": str(error.reason),
                    },
                )

        def _target_url(self) -> str:
            request_url = urlsplit(self.path)
            request_path = request_url.path or "/"
            target_path = f"{destination_base_path}{request_path}"
            return urlunsplit(
                (
                    destination.scheme,
                    destination.netloc,
                    target_path,
                    request_url.query,
                    "",
                )
            )

        def _read_body(self) -> bytes | None:
            content_length = self.headers.get("Content-Length")
            if not content_length:
                return None
            return self.rfile.read(int(content_length))

        def _forward_headers(self) -> dict[str, str]:
            headers: dict[str, str] = {}
            for key, value in self.headers.items():
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower == "host":
                    continue
                headers[key] = value
            headers["Host"] = destination.netloc
            return headers

        def _send_response(
            self,
            status_code: int,
            response_headers: list[tuple[str, str]],
            response_body: bytes,
        ) -> None:
            self.send_response(status_code)
            for key, value in response_headers:
                if not should_forward_response_header(key):
                    continue
                if key.lower() == "set-cookie":
                    value = rewrite_set_cookie_header(value, proxy.origin)
                self.send_header(key, value)
            self._send_cors_headers()
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if self.command.upper() != "HEAD":
                self.wfile.write(response_body)

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.send_header("Connection", "close")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command.upper() != "HEAD":
                self.wfile.write(body)

        def _send_proxy_error(self, status_code: int, error: str, detail: str) -> None:
            try:
                self._send_json(
                    status_code,
                    {
                        "error": error,
                        "detail": detail,
                    },
                )
            except (BrokenPipeError, ConnectionResetError):
                safe_log("Client disconnected before proxy error response was sent.")

        def _send_empty(self, status_code: int) -> None:
            self.send_response(status_code)
            self._send_cors_headers()
            self.send_header("Connection", "close")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_cors_headers(self) -> None:
            request_headers = self.headers.get("Access-Control-Request-Headers")
            for key, value in cors_headers(
                request_origin=self.headers.get("Origin"),
                request_headers=request_headers,
            ).items():
                self.send_header(key, value)

    return ProxyRequestHandler


def should_forward_response_header(header_name: str) -> bool:
    lower = header_name.lower()
    blocked = HOP_BY_HOP_HEADERS | CORS_RESPONSE_HEADERS | {"content-length", "server", "date"}
    return lower not in blocked


def cors_headers(request_origin: str | None, request_headers: str | None = None) -> dict[str, str]:
    headers = {
        "Access-Control-Allow-Origin": request_origin or "*",
        "Access-Control-Allow-Methods": ALLOWED_CORS_METHODS,
        "Access-Control-Allow-Headers": request_headers or "*",
        "Access-Control-Allow-Credentials": "true",
    }
    if request_origin:
        headers["Vary"] = "Origin"
    return headers


def rewrite_set_cookie_header(header_value: str, origin: str) -> str:
    origin_parts = urlsplit(origin)
    rewritten_parts: list[str] = []

    for part in header_value.split(";"):
        stripped = part.strip()
        lower = stripped.lower()
        if lower.startswith("domain="):
            continue
        if origin_parts.scheme == "http" and lower == "secure":
            continue
        if origin_parts.scheme == "http" and lower == "samesite=none":
            rewritten_parts.append("SameSite=Lax")
            continue
        rewritten_parts.append(stripped)

    return "; ".join(rewritten_parts)


def safe_log(message: str) -> None:
    try:
        print(message, file=sys.stderr, flush=True)
    except (BrokenPipeError, OSError):
        pass
