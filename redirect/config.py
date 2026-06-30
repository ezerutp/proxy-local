from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import ProxyConfig, RedirectError


def redirect_home() -> Path:
    return Path(os.environ.get("REDIRECT_HOME", Path.home() / ".redirect")).expanduser()


def config_path() -> Path:
    return redirect_home() / "config.json"


def state_path() -> Path:
    return redirect_home() / "state.json"


def log_path(proxy_id: str) -> Path:
    return redirect_home() / "logs" / f"{proxy_id}.log"


def load_proxies() -> list[ProxyConfig]:
    path = config_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return [ProxyConfig.from_dict(item) for item in payload.get("proxies", [])]


def save_proxies(proxies: list[ProxyConfig]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"proxies": [proxy.to_dict() for proxy in proxies]}
    _write_json(path, payload)


def find_proxy(proxies: list[ProxyConfig], proxy_id: str) -> ProxyConfig:
    for proxy in proxies:
        if proxy.id == proxy_id:
            return proxy
    raise RedirectError(f"Proxy '{proxy_id}' does not exist.")


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {"processes": {}}
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    payload.setdefault("processes", {})
    return payload


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, state)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")
    temporary.replace(path)
