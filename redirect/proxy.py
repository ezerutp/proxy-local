from __future__ import annotations

import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .models import ProxyConfig, SAFE_METHODS, origin_host_port


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}

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


def is_port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"localhost", "0.0.0.0"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0


def serve_proxy(proxy: ProxyConfig) -> None:
    host, port = origin_host_port(proxy.origin)
    handler = build_proxy_handler(proxy)
    server = ThreadingHTTPServer((host, port), handler)
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
            self._handle_proxy_request()

        def do_HEAD(self) -> None:
            self._handle_proxy_request()

        def do_OPTIONS(self) -> None:
            if self.headers.get("Access-Control-Request-Method"):
                self._send_empty(204)
                return
            self._handle_proxy_request()

        def do_POST(self) -> None:
            self._handle_proxy_request()

        def do_PUT(self) -> None:
            self._handle_proxy_request()

        def do_PATCH(self) -> None:
            self._handle_proxy_request()

        def do_DELETE(self) -> None:
            self._handle_proxy_request()

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format % args}", flush=True)

        def _handle_proxy_request(self) -> None:
            method = self.command.upper()
            if not proxy.unsafe and method not in SAFE_METHODS:
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
                    response_headers = dict(response.headers.items())
                    self._send_response(response.status, response_headers, response_body)
            except HTTPError as error:
                response_body = b"" if method == "HEAD" else error.read()
                response_headers = dict(error.headers.items())
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
            response_headers: dict[str, str],
            response_body: bytes,
        ) -> None:
            self.send_response(status_code)
            blocked = HOP_BY_HOP_HEADERS | {"content-length", "server", "date"}
            for key, value in response_headers.items():
                if key.lower() in blocked:
                    continue
                self.send_header(key, value)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if self.command.upper() != "HEAD":
                self.wfile.write(response_body)

        def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command.upper() != "HEAD":
                self.wfile.write(body)

        def _send_empty(self, status_code: int) -> None:
            self.send_response(status_code)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return ProxyRequestHandler
