from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SUPPORTED_SCHEMES = {"http", "https"}


class RedirectError(Exception):
    """User-facing error raised by the redirect CLI."""


@dataclass(slots=True)
class ProxyConfig:
    id: str
    origin: str
    destination: str
    enabled: bool = False
    unsafe: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProxyConfig":
        return cls(
            id=str(value["id"]),
            origin=str(value["origin"]),
            destination=str(value["destination"]),
            enabled=bool(value.get("enabled", False)),
            unsafe=bool(value.get("unsafe", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "origin": self.origin,
            "destination": self.destination,
            "enabled": self.enabled,
            "unsafe": self.unsafe,
        }


def validate_id(proxy_id: str) -> str:
    if not proxy_id or not proxy_id.strip():
        raise RedirectError("Proxy id cannot be empty.")
    if any(char.isspace() for char in proxy_id):
        raise RedirectError("Proxy id cannot contain whitespace.")
    return proxy_id.strip()


def validate_origin(origin: str) -> str:
    parsed = urlparse(origin)
    if parsed.scheme not in SUPPORTED_SCHEMES or not parsed.hostname or parsed.port is None:
        raise RedirectError(
            f"Invalid origin '{origin}'. Origin must be a valid http or https URL with host and port."
        )
    return _without_trailing_slash(origin)


def validate_destination(destination: str) -> str:
    parsed = urlparse(destination)
    if parsed.scheme not in SUPPORTED_SCHEMES or not parsed.hostname:
        raise RedirectError(
            f"Invalid destination '{destination}'. Destination must be a valid http or https URL."
        )
    return _without_trailing_slash(destination)


def origin_host_port(origin: str) -> tuple[str, int]:
    parsed = urlparse(origin)
    if not parsed.hostname or parsed.port is None:
        raise RedirectError(f"Invalid origin '{origin}'.")
    return parsed.hostname, parsed.port


def _without_trailing_slash(url: str) -> str:
    return url.rstrip("/") if url.endswith("/") else url
