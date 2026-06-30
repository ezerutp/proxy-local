from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from redirect import cli
from redirect.cli import parse_key_values
from redirect.config import config_path, load_proxies, save_proxies
from redirect.models import ProxyConfig, RedirectError, validate_destination, validate_origin
from redirect.proxy import (
    RedirectHTTPServer,
    cors_headers,
    rewrite_set_cookie_header,
    should_forward_response_header,
)


class RedirectTests(unittest.TestCase):
    def test_parse_key_values(self) -> None:
        values = parse_key_values(
            [
                "id=qa-api",
                "origin=http://localhost:8080",
                "destination=https://api.ejemplo.xyz",
            ]
        )
        self.assertEqual(values["id"], "qa-api")
        self.assertEqual(values["origin"], "http://localhost:8080")
        self.assertEqual(values["destination"], "https://api.ejemplo.xyz")

    def test_invalid_key_value_pair(self) -> None:
        with self.assertRaises(RedirectError):
            parse_key_values(["origin"])

    def test_validate_origin_requires_scheme_host_and_port(self) -> None:
        self.assertEqual(validate_origin("http://localhost:8080"), "http://localhost:8080")
        with self.assertRaises(RedirectError):
            validate_origin("localhost:8080")
        with self.assertRaises(RedirectError):
            validate_origin("http://localhost")

    def test_validate_destination_accepts_http_and_https(self) -> None:
        self.assertEqual(
            validate_destination("https://api.ejemplo.xyz"),
            "https://api.ejemplo.xyz",
        )
        with self.assertRaises(RedirectError):
            validate_destination("ftp://api.ejemplo.xyz")

    def test_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"REDIRECT_HOME": directory}):
                proxy = ProxyConfig(
                    id="qa-api",
                    origin="http://localhost:8080",
                    destination="https://api.ejemplo.xyz",
                )
                save_proxies([proxy])
                self.assertEqual(config_path(), Path(directory) / "config.json")
                loaded = load_proxies()
                self.assertEqual(loaded, [proxy])

    def test_background_command_uses_module_when_running_with_python(self) -> None:
        with patch.object(cli.sys, "executable", "/usr/bin/python3"):
            self.assertEqual(
                cli.background_proxy_command("qa-api"),
                ["/usr/bin/python3", "-m", "redirect.cli", "--serve", "qa-api"],
            )

    def test_background_command_uses_direct_serve_when_packaged(self) -> None:
        with patch.object(cli.sys, "executable", "/home/ezer/.local/share/redirect/briefcase/app/usr/bin/redirect"):
            self.assertEqual(
                cli.background_proxy_command("qa-api"),
                [
                    "/home/ezer/.local/share/redirect/briefcase/app/usr/bin/redirect",
                    "--serve",
                    "qa-api",
                ],
            )

    def test_response_header_filter_removes_upstream_cors(self) -> None:
        self.assertFalse(should_forward_response_header("Access-Control-Allow-Origin"))
        self.assertFalse(should_forward_response_header("access-control-allow-methods"))
        self.assertFalse(should_forward_response_header("Access-Control-Allow-Headers"))
        self.assertTrue(should_forward_response_header("Content-Type"))

    def test_cors_headers_reflect_request_origin_for_credentials(self) -> None:
        headers = cors_headers(
            request_origin="http://localhost:5173",
            request_headers="authorization, content-type",
        )
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(headers["Access-Control-Allow-Credentials"], "true")
        self.assertEqual(headers["Access-Control-Allow-Headers"], "authorization, content-type")
        self.assertEqual(headers["Vary"], "Origin")

    def test_set_cookie_rewrite_removes_remote_domain_for_localhost(self) -> None:
        cookie = rewrite_set_cookie_header(
            "session=abc; Domain=qa-api.jayaram.xyz; Path=/; Secure; SameSite=None; HttpOnly",
            "http://localhost:8080",
        )
        self.assertEqual(cookie, "session=abc; Path=/; SameSite=Lax; HttpOnly")

    def test_server_uses_daemon_threads(self) -> None:
        self.assertTrue(RedirectHTTPServer.daemon_threads)


if __name__ == "__main__":
    unittest.main()
