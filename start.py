#!/usr/bin/env python3
"""Launch Docker Compose: agent + Redis (spawned if REDIS_URL is unset).

- OPENAI_API_KEY required
- AGENT_PORT optional (random free port if unset)
- REDIS_URL optional:
    unset  → start an embedded Redis container (profile embedded-redis)
    set    → use that Redis; do not spawn a container
- PUBLIC_REDIS_URL optional (defaults from embedded port or REDIS_URL)

Usage:
  ./start.py
  ./start.py -d
  REDIS_URL=redis://localhost:6379/0 ./start.py
  AGENT_PORT=18080 ./start.py
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (stdlib only — runs before any venv)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _resolve_port(env_name: str, taken: set[int]) -> int:
    raw = os.environ.get(env_name, "").strip()
    if raw:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise SystemExit(f"{env_name}={port} is not a valid TCP port")
        taken.add(port)
        return port

    for _ in range(50):
        port = _free_port()
        if port not in taken:
            taken.add(port)
            return port
    raise SystemExit(f"Could not allocate a free port for {env_name}")


def _docker_reachable_redis_url(url: str) -> str:
    """Rewrite localhost Redis URLs so the agent container can reach the host."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in {"localhost", "127.0.0.1"}:
        return url
    port = parsed.port
    netloc = f"host.docker.internal:{port}" if port else "host.docker.internal"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def main(argv: list[str]) -> int:
    _load_dotenv(ROOT / ".env")

    if shutil.which("docker") is None:
        print("Docker is required. Install Docker Desktop / Engine.", file=sys.stderr)
        return 1
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Docker Compose v2 is required (`docker compose`).", file=sys.stderr)
        return 1

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print(
            "OPENAI_API_KEY is required. Copy .env.example to .env and set your key.",
            file=sys.stderr,
        )
        return 1

    taken: set[int] = set()
    agent_port = _resolve_port("AGENT_PORT", taken)

    # Optional external Redis. If unset, spawn embedded Redis in Compose.
    external_redis = (
        os.environ.get("REDIS_URL", "").strip() or os.environ.get("PUBLIC_REDIS_URL", "").strip()
    )
    spawn_redis = not bool(external_redis)

    if spawn_redis:
        redis_port = _resolve_port("REDIS_PORT", taken)
        public_redis = (
            os.environ.get("PUBLIC_REDIS_URL", "").strip() or f"redis://localhost:{redis_port}/0"
        )
        agent_redis = "redis://redis:6379/0"
    else:
        redis_port = 0
        public_redis = os.environ.get("PUBLIC_REDIS_URL", "").strip() or external_redis
        # Prefer explicit REDIS_URL for the container client; rewrite localhost.
        explicit_client = os.environ.get("REDIS_URL", "").strip()
        agent_redis = _docker_reachable_redis_url(explicit_client or public_redis)

    public_base = os.environ.get("PUBLIC_BASE_URL", "").strip() or f"http://localhost:{agent_port}"

    env = os.environ.copy()
    env["AGENT_PORT"] = str(agent_port)
    env["REDIS_PORT"] = str(redis_port if redis_port else 0)
    env["PUBLIC_BASE_URL"] = public_base
    env["PUBLIC_REDIS_URL"] = public_redis
    env["REDIS_URL"] = agent_redis

    compose_args = argv[1:] if argv[1:] else ["up", "--build"]
    if compose_args and compose_args[0].startswith("-"):
        compose_args = ["up", "--build", *compose_args]

    print("Starting stack with Docker Compose…")
    print()
    print("Host ports / resources")
    print(f"  API health    {public_base}/api/health")
    print(f"  OpenAPI docs  {public_base}/docs")
    print(f"  Chat API      POST {public_base}/api/chat")
    print(f"  Agent port    {agent_port}  (set AGENT_PORT to pin)")
    if spawn_redis:
        print(f"  Redis         {public_redis}  (embedded; set REDIS_PORT to pin)")
        print("  Redis mode    spawned by Compose (profile: embedded-redis)")
    else:
        print(f"  Redis         {public_redis}  (external; not spawned)")
        print(f"  Redis (agent) {agent_redis}")
    print("  Redis creds   (none assumed — configure auth on external Redis if needed)")
    print("  CLI           python -m src.cli  (uses PUBLIC_REDIS_URL on the host)")
    print()

    runtime = ROOT / ".env.runtime"
    runtime_lines = [
        f"AGENT_PORT={agent_port}",
        f"REDIS_PORT={redis_port}",
        f"PUBLIC_BASE_URL={public_base}",
        f"PUBLIC_REDIS_URL={public_redis}",
        f"REDIS_URL={agent_redis}",
        f"EMBEDDED_REDIS={'1' if spawn_redis else '0'}",
        "",
    ]
    runtime.write_text("\n".join(runtime_lines), encoding="utf-8")

    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(runtime),
    ]
    if spawn_redis:
        cmd.extend(["--profile", "embedded-redis"])
    cmd.extend(compose_args)
    return subprocess.call(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
