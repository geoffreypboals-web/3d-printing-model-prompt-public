"""
Project: 3D Printing Model Prompt
File: launch.py
Description: Suite-aware launcher, the same script shape as the
    other suite repos' launch.py, copied on purpose rather than shared.
    docker-compose.yml used to publish fixed "8000:8000" and "11434:11434";
    `up` now finds free host ports near those (or uses APP_HOST_PORT /
    OLLAMA_HOST_PORT from the environment or .env, which may pin a host IP
    such as 127.0.0.1:8000), records them in ~/.suite/ports.json, and starts
    the stack. `open` opens the web UI in your browser.

    Two modes, picked from .env (or --host-ollama / --bundled-ollama):
      * bundled: OLLAMA_HOST unset or http://ollama:..., and LLM_PROVIDER
        isn't claude -> starts the app and the bundled ollama service.
      * host: OLLAMA_HOST points anywhere else (a host Ollama, e.g. the GPU
        server's), or LLM_PROVIDER=claude -> `up -d --build --no-deps app`,
        so the bundled ollama service is never started by accident and no
        port is reserved for it.
Inputs: command line (up/open/status/down/relocate, --host-ollama,
    --bundled-ollama); APP_HOST_PORT, OLLAMA_HOST_PORT, OLLAMA_HOST and
    LLM_PROVIDER from the environment or .env; docker-compose.yml and, when
    present, docker-compose.override.yml.
Outputs: running containers; ~/.suite/ports.json (this project's entry); a
    browser tab on `open`.
Troubleshooting:
    - The bundled ollama started on a host that has its own Ollama: set
      OLLAMA_HOST in .env (host mode), then `python launch.py down` and `up`.
    - "Ports not resolved yet" on open: run `python launch.py up` first.
    - The page doesn't load: `python launch.py status`, then
      `docker compose logs app`.

Usage:
    python launch.py up       find free ports, start the stack
    python launch.py open     open the web UI in your browser
    python launch.py status   show the resolved ports and whether they're up
    python launch.py down     stop
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

PROJECT = "3d-printing-model-prompt"
COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.yml"

APP = {
    "key": "app",
    "compose_service": "app",
    "default_port": 8000,
    "container_port": 8000,
    "category": "internal",
    "open_path": "/",
}
OLLAMA = {
    "key": "ollama",
    "compose_service": "ollama",
    "default_port": 11434,
    "container_port": 11434,
    "category": "internal",  # the app reaches it on the compose network (http://ollama:11434)
}
SERVICES = [APP, OLLAMA]  # bundled mode; host mode uses [APP] only (see services_for())

REGISTRY_PATH = Path.home() / ".suite" / "ports.json"


def _compose_files() -> list:
    """`-f` turns off compose's automatic docker-compose.override.yml pickup,
    so add the override back when a host has one (a host's override may
    narrow what gets published; dropping it once exposed a port on 0.0.0.0).

    Returns:
        The `-f` arguments for docker compose.
    """
    files = ["-f", str(COMPOSE_FILE)]
    override = COMPOSE_FILE.with_name("docker-compose.override.yml")
    if override.exists():
        files += ["-f", str(override)]
    return files


def _pinned_host_port(service: dict):
    """A <KEY>_HOST_PORT the user set in the environment or .env wins over
    probing. It can pin a host IP ("127.0.0.1:4000") that a bare port number
    can't express, so exporting the probed port in its place widened the bind
    to 0.0.0.0. Returns the raw value, or None when nothing is pinned."""
    var = f"{service['key'].upper().replace('-', '_')}_HOST_PORT"
    if os.environ.get(var, "").strip():
        return os.environ[var].strip()
    env_file = COMPOSE_FILE.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{var}=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def _env_value(name: str):
    """A setting from the environment, else from .env next to the compose file.

    Args:
        name: the variable name.
    Returns:
        The stripped value, or None when it's unset or empty.
    """
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    env_file = COMPOSE_FILE.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def host_ollama_mode(force_host: bool = False, force_bundled: bool = False) -> bool:
    """True when the app should run without the bundled ollama service.

    Args:
        force_host: --host-ollama was given.
        force_bundled: --bundled-ollama was given.
    Returns:
        True for host mode (`up --no-deps app`), False for the bundled stack.
    """
    if force_host or force_bundled:
        return force_host
    if (_env_value("LLM_PROVIDER") or "").lower() == "claude":
        return True
    host = _env_value("OLLAMA_HOST")
    return bool(host) and not host.startswith("http://ollama:")


def services_for(host_mode: bool) -> list:
    """The services this launch publishes: the app, plus Ollama when bundled."""
    return [APP] if host_mode else [APP, OLLAMA]


def _is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Why both
    checks are needed (Docker Desktop for Windows quirk: bind() alone can
    succeed on a port a container is already publishing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        if probe.connect_ex((host, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _registry_claimed_ports(reg: dict, exclude_project: str | None = None) -> set:
    claimed = set()
    for proj, services in reg.items():
        if proj == exclude_project:
            continue
        for svc in services.values():
            claimed.add(svc.get("port"))
    return claimed


def resolve_port(service: dict, reg: dict, allow_reassign_oauth: bool = False) -> int:
    pinned = _pinned_host_port(service)
    if pinned:
        return int(pinned.rsplit(":", 1)[-1])
    default = service["default_port"]
    claimed = _registry_claimed_ports(reg, exclude_project=PROJECT)

    prior = reg.get(PROJECT, {}).get(service["key"], {}).get("port")
    if prior and prior not in claimed and (prior == default or _is_port_free(prior)):
        return prior

    if service["category"] == "oauth_callback":
        if default not in claimed and _is_port_free(default):
            return default
        if not allow_reassign_oauth:
            raise SystemExit(
                f"❌ Port {default} (this project's OAuth redirect URI) is not free, and it's "
                f"registered with an external provider as a fixed callback URL -- silently moving "
                f"it would break login. Free port {default}, or re-run with --allow-reassign-oauth "
                f"if you've already updated the redirect URI registered with the provider to match "
                f"whatever port gets picked."
            )

    if default not in claimed and _is_port_free(default):
        return default
    for candidate in range(default + 1, default + 51):
        if candidate in claimed:
            continue
        if _is_port_free(candidate):
            return candidate
    raise SystemExit(f"❌ No free port found near {default} after scanning 50 candidates.")


def resolve_all(allow_reassign_oauth: bool = False, services: list | None = None) -> dict:
    services = SERVICES if services is None else services
    reg = _load_registry()
    resolved = {}
    for service in services:
        port = resolve_port(service, reg, allow_reassign_oauth)
        resolved[service["key"]] = port
        if port != service["default_port"]:
            print(f"⚠ Port {service['default_port']} was taken -- {PROJECT}/{service['key']} will use {port} instead.")
            if service["category"] == "oauth_callback":
                print(
                    f"   You MUST update the redirect URI registered with the provider to use "
                    f"port {port} instead of {service['default_port']}, or login will fail."
                )
    reg[PROJECT] = {svc["key"]: {"port": resolved[svc["key"]], "category": svc["category"]} for svc in services}
    _save_registry(reg)
    return resolved


def _env_var_name(service_key: str) -> str:
    return f"{service_key.upper().replace('-', '_')}_HOST_PORT"


def cmd_up(args):
    host_mode = host_ollama_mode(args.host_ollama, args.bundled_ollama)
    services = services_for(host_mode)
    resolved = resolve_all(args.allow_reassign_oauth, services)
    env = os.environ.copy()
    for service in services:
        env[_env_var_name(service["key"])] = _pinned_host_port(service) or str(resolved[service["key"]])
        print(f"✓ {PROJECT}/{service['key']}: http://localhost:{resolved[service['key']]}")
    if host_mode:
        print(
            "Host mode: using OLLAMA_HOST from .env (or LLM_PROVIDER=claude); "
            "the bundled ollama service is not started."
        )
        cmd = ["docker", "compose", *_compose_files(), "up", "-d", "--build", "--no-deps", "app"]
    else:
        # --build: `up -d` alone keeps running a stale image after a code change.
        cmd = ["docker", "compose", *_compose_files(), "up", "-d", "--build"]
    subprocess.run(cmd, env=env, check=True)
    if not host_mode:
        print("First run? Pull the model: docker compose exec ollama ollama pull llama3.1")
    print("\nStarted. Run `python launch.py open` to view it, or `python launch.py status` to check.")


def cmd_open(args):
    services = _load_registry().get(PROJECT, {})
    if not services:
        print("Not started yet (or ports were never resolved) -- run `python launch.py up` first.")
        return
    port = services.get(APP["key"], {}).get("port", APP["default_port"])
    url = f"http://localhost:{port}{APP['open_path']}"
    print(f"Opening {url} ...")
    webbrowser.open(url)


def cmd_status(args):
    reg = _load_registry()
    services = reg.get(PROJECT, {})
    if not services:
        print(f"{PROJECT}: never started via launch.py.")
        return
    for service in SERVICES:  # host mode has no ollama entry; skipped below
        entry = services.get(service["key"])
        if not entry:
            continue
        port = entry["port"]
        up = not _is_port_free(port)
        print(f"{PROJECT}/{service['key']}: port {port} -- {'UP' if up else 'not running'}")


def cmd_down(args):
    subprocess.run(["docker", "compose", *_compose_files(), "down"], check=True)


def cmd_relocate(args):
    """Forces a fresh port scan, ignoring this project's previously-
    resolved port -- use this BEFORE installing/starting something else
    you know will want the same port. Reports the new port(s) clearly; if
    it's an oauth_callback port you'll also need --allow-reassign-oauth
    and to update the redirect URI registered with the provider."""
    reg = _load_registry()
    reg.pop(PROJECT, None)
    _save_registry(reg)
    services = services_for(host_ollama_mode(args.host_ollama, args.bundled_ollama))
    resolved = resolve_all(args.allow_reassign_oauth, services)
    print(f"\n{PROJECT} relocated:")
    for key, port in resolved.items():
        print(f"  {key}: {port}")
    print(
        "\nRestart this service for the new port to take effect "
        "(`python launch.py down` then `up`, or just `up` again if it wasn't running)."
    )


def main():
    parser = argparse.ArgumentParser(description=f"Suite-aware launcher for {PROJECT}.")
    parser.add_argument("command", choices=["up", "open", "status", "down", "relocate"])
    parser.add_argument(
        "--allow-reassign-oauth",
        action="store_true",
        help="Allow moving the OAuth-callback port off its default -- you must "
        "then update the redirect URI registered with the provider to match.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--host-ollama",
        action="store_true",
        help="Run only the app against OLLAMA_HOST (never start the bundled ollama).",
    )
    mode.add_argument(
        "--bundled-ollama", action="store_true", help="Start the bundled ollama service even if OLLAMA_HOST is set."
    )
    args = parser.parse_args()
    {"up": cmd_up, "open": cmd_open, "status": cmd_status, "down": cmd_down, "relocate": cmd_relocate}[args.command](
        args
    )


if __name__ == "__main__":
    sys.exit(main())
