from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from redirect.cli import parse_key_values
from redirect.config import config_path, load_proxies, save_proxies
from redirect.models import ProxyConfig, RedirectError, validate_destination, validate_origin


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


if __name__ == "__main__":
    unittest.main()
