from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from .config import (
    find_proxy,
    load_proxies,
    load_state,
    log_path,
    save_proxies,
    save_state,
)
from .models import (
    ProxyConfig,
    RedirectError,
    origin_host_port,
    validate_destination,
    validate_id,
    validate_origin,
)
from .proxy import is_port_in_use, serve_proxy


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.serve:
            return serve_existing(args.serve)
        if args.set_values is not None:
            return set_proxy(args.set_values)
        if args.temp_values is not None:
            return temp_proxy(args.temp_values, args.unsafe)
        if args.list:
            return list_proxies()
        if args.enable:
            return enable_proxy(args.enable, args.unsafe)
        if args.disable:
            return disable_proxy(args.disable)
        if args.delete:
            return delete_proxy(args.delete)
        parser.print_help()
        return 0
    except RedirectError as error:
        print(error, file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redirect",
        description="Manage local proxies that redirect local origins to remote APIs.",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--set", dest="set_values", nargs="+", metavar="key=value")
    actions.add_argument("-t", "--temp", dest="temp_values", nargs="+", metavar="key=value")
    actions.add_argument("-l", "--list", action="store_true")
    actions.add_argument("-e", "--enable", metavar="ID")
    actions.add_argument("--disable", metavar="ID")
    actions.add_argument("-d", "--delete", metavar="ID")
    actions.add_argument("--serve", metavar="ID", help=argparse.SUPPRESS)
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Allow all HTTP methods. By default, only GET, HEAD and OPTIONS are allowed.",
    )
    return parser


def set_proxy(values: list[str]) -> int:
    options = parse_key_values(values)
    proxy_id = validate_id(required(options, "id"))
    origin = validate_origin(required(options, "origin"))
    destination = validate_destination(required(options, "destination"))

    proxies = load_proxies()
    if any(proxy.id == proxy_id for proxy in proxies):
        raise RedirectError(f"A proxy with id '{proxy_id}' already exists.")
    if any(proxy.destination == destination for proxy in proxies):
        raise RedirectError(f"A proxy with destination '{destination}' already exists.")

    proxies.append(
        ProxyConfig(
            id=proxy_id,
            origin=origin,
            destination=destination,
            enabled=False,
            unsafe=False,
        )
    )
    save_proxies(proxies)
    print(f"Proxy '{proxy_id}' saved as inactive.")
    return 0


def temp_proxy(values: list[str], unsafe: bool) -> int:
    options = parse_key_values(values)
    origin = validate_origin(required(options, "origin"))
    destination = validate_destination(required(options, "destination"))
    proxy = ProxyConfig(
        id="temporary",
        origin=origin,
        destination=destination,
        enabled=True,
        unsafe=unsafe,
    )
    ensure_port_available(proxy)
    print(
        f"Temporary proxy listening at {proxy.origin} -> {proxy.destination} "
        f"({'unsafe' if proxy.unsafe else 'safe'} mode). Press Ctrl+C to stop."
    )
    serve_proxy(proxy)
    return 0


def list_proxies() -> int:
    proxies = load_proxies()
    state = load_state()
    changed = cleanup_dead_processes(proxies, state)
    if changed:
        save_proxies(proxies)
        save_state(state)

    if not proxies:
        print("No proxies configured.")
        return 0

    rows = [
        (
            "ID",
            "ORIGIN",
            "DESTINATION",
            "STATUS",
            "SAFE MODE",
        )
    ]
    for proxy in proxies:
        running = is_proxy_running(state, proxy.id)
        rows.append(
            (
                proxy.id,
                proxy.origin,
                proxy.destination,
                "active" if running else "inactive",
                "disabled" if proxy.unsafe else "enabled",
            )
        )
    print_table(rows)
    return 0


def enable_proxy(proxy_id: str, unsafe: bool) -> int:
    proxy_id = validate_id(proxy_id)
    proxies = load_proxies()
    state = load_state()
    cleanup_dead_processes(proxies, state)
    proxy = find_proxy(proxies, proxy_id)

    if is_proxy_running(state, proxy.id):
        if proxy.unsafe == unsafe:
            print(f"Proxy '{proxy.id}' is already active.")
            save_proxies(proxies)
            save_state(state)
            return 0
        stop_process(state, proxy.id)

    proxy.unsafe = unsafe
    ensure_no_active_origin_conflict(proxy, proxies, state)
    ensure_port_available(proxy)
    process = start_background_proxy(proxy)
    if not wait_for_proxy_start(proxy, process):
        raise RedirectError(
            f"Proxy '{proxy.id}' failed to start. Check the log at {log_path(proxy.id)}."
        )

    proxy.enabled = True
    state.setdefault("processes", {})[proxy.id] = {
        "pid": process.pid,
        "origin": proxy.origin,
        "destination": proxy.destination,
    }
    save_proxies(proxies)
    save_state(state)
    print(
        f"Proxy '{proxy.id}' enabled at {proxy.origin} -> {proxy.destination} "
        f"({'unsafe' if proxy.unsafe else 'safe'} mode)."
    )
    return 0


def disable_proxy(proxy_id: str) -> int:
    proxy_id = validate_id(proxy_id)
    proxies = load_proxies()
    state = load_state()
    cleanup_dead_processes(proxies, state)
    proxy = find_proxy(proxies, proxy_id)
    stop_process(state, proxy.id)
    proxy.enabled = False
    save_proxies(proxies)
    save_state(state)
    print(f"Proxy '{proxy.id}' disabled.")
    return 0


def delete_proxy(proxy_id: str) -> int:
    proxy_id = validate_id(proxy_id)
    proxies = load_proxies()
    state = load_state()
    cleanup_dead_processes(proxies, state)
    proxy = find_proxy(proxies, proxy_id)
    stop_process(state, proxy.id)
    remaining = [item for item in proxies if item.id != proxy.id]
    save_proxies(remaining)
    save_state(state)
    print(f"Proxy '{proxy.id}' deleted.")
    return 0


def serve_existing(proxy_id: str) -> int:
    proxies = load_proxies()
    proxy = find_proxy(proxies, proxy_id)
    serve_proxy(proxy)
    return 0


def parse_key_values(values: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise RedirectError(f"Invalid option '{value}'. Expected key=value.")
        key, item = value.split("=", 1)
        if not key or not item:
            raise RedirectError(f"Invalid option '{value}'. Expected key=value.")
        options[key] = item
    return options


def required(options: dict[str, str], key: str) -> str:
    try:
        return options[key]
    except KeyError as error:
        raise RedirectError(f"Missing required option '{key}'.") from error


def ensure_no_active_origin_conflict(
    candidate: ProxyConfig,
    proxies: list[ProxyConfig],
    state: dict,
) -> None:
    candidate_host, candidate_port = origin_host_port(candidate.origin)
    for proxy in proxies:
        if proxy.id == candidate.id or not is_proxy_running(state, proxy.id):
            continue
        host, port = origin_host_port(proxy.origin)
        if host == candidate_host and port == candidate_port:
            raise RedirectError(
                f"Cannot enable proxy '{candidate.id}' because origin {candidate.origin} "
                f"is already used by active proxy '{proxy.id}'."
            )


def ensure_port_available(proxy: ProxyConfig) -> None:
    host, port = origin_host_port(proxy.origin)
    try:
        port_in_use = is_port_in_use(host, port)
    except OSError as error:
        raise RedirectError(
            f"Cannot check port {port} for proxy '{proxy.id}': {error}."
        ) from error
    if port_in_use:
        raise RedirectError(
            f"Cannot enable proxy '{proxy.id}' because port {port} is already in use."
        )


def start_background_proxy(proxy: ProxyConfig) -> subprocess.Popen:
    path = log_path(proxy.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as log_file:
        return subprocess.Popen(
            background_proxy_command(proxy.id),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def wait_for_proxy_start(
    proxy: ProxyConfig,
    process: subprocess.Popen,
    timeout_seconds: float = 5,
) -> bool:
    host, port = origin_host_port(proxy.origin)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            if is_port_in_use(host, port):
                return True
        except OSError:
            return False
        time.sleep(0.1)
    return False


def background_proxy_command(proxy_id: str) -> list[str]:
    executable_name = Path(sys.executable).name.lower()
    if executable_name.startswith("python"):
        return [sys.executable, "-m", "redirect.cli", "--serve", proxy_id]
    return [sys.executable, "--serve", proxy_id]


def cleanup_dead_processes(proxies: list[ProxyConfig], state: dict) -> bool:
    changed = False
    processes = state.setdefault("processes", {})
    for proxy in proxies:
        if proxy.id not in processes:
            if proxy.enabled:
                proxy.enabled = False
                changed = True
            continue
        if not pid_is_alive(processes[proxy.id].get("pid")):
            del processes[proxy.id]
            proxy.enabled = False
            changed = True
    return changed


def is_proxy_running(state: dict, proxy_id: str) -> bool:
    process = state.setdefault("processes", {}).get(proxy_id)
    return bool(process and pid_is_alive(process.get("pid")))


def stop_process(state: dict, proxy_id: str) -> None:
    process = state.setdefault("processes", {}).pop(proxy_id, None)
    if not process:
        return
    pid = process.get("pid")
    if not pid_is_alive(pid):
        return
    os.kill(int(pid), signal.SIGTERM)
    deadline = time.time() + 3
    while time.time() < deadline:
        if not pid_is_alive(pid):
            return
        time.sleep(0.1)
    os.kill(int(pid), signal.SIGKILL)


def pid_is_alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def print_table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


if __name__ == "__main__":
    raise SystemExit(main())
