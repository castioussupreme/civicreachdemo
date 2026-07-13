#!/usr/bin/env python3
"""Launch Docker Compose: agent + Redis + Qdrant (spawned if URLs unset).

- OPENAI_API_KEY required (chat + embeddings)
- AGENT_PORT optional (random free port if unset)
- REDIS_URL optional:
    unset  → start embedded Redis (profile embedded-redis)
    set    → use that Redis; do not spawn a container
- QDRANT_URL optional:
    unset  → start embedded Qdrant (profile embedded-qdrant)
    set    → use that Qdrant; do not spawn a container

Usage:
  ./start.py              # foreground; exits when agent exits (aborts whole stack)
  ./start.py -d           # detached; make returns immediately
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

# Paths the agent image and runtime need (fail fast with a clear message).
_REQUIRED_PATHS = (
    ROOT / "Dockerfile",
    ROOT / "compose.yaml",
    ROOT / "pyproject.toml",
    ROOT / "src",
    ROOT / "programs" / "registry.yaml",
)


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


def _docker_reachable_url(url: str, *, default_scheme_port: int | None = None) -> str:
    """Rewrite localhost URLs so the agent container can reach the host."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in {"localhost", "127.0.0.1"}:
        return url
    port = parsed.port or default_scheme_port
    netloc = f"host.docker.internal:{port}" if port else "host.docker.internal"
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def _preflight() -> list[str]:
    """Return human-readable errors if the repo is not ready to build/run."""
    errors: list[str] = []
    for path in _REQUIRED_PATHS:
        if not path.exists():
            errors.append(f"missing required path: {path.relative_to(ROOT)}")

    programs = ROOT / "programs"
    if programs.is_dir():
        packs = [p for p in programs.iterdir() if p.is_dir() and (p / "program.yaml").is_file()]
        if not packs:
            errors.append(
                "programs/ has no packs with program.yaml "
                "(expected e.g. programs/nc-fns/program.yaml)"
            )
        for pack in packs:
            if not (pack / "rules").is_dir() or not any((pack / "rules").glob("*.yaml")):
                errors.append(f"program pack {pack.name}: no rules/*.yaml")
            if not (pack / "knowledge" / "manifest.json").is_file():
                errors.append(f"program pack {pack.name}: missing knowledge/manifest.json")

    # Stale layout (pre multi-program) that breaks Docker COPY if still referenced
    if (ROOT / "knowledge").exists() and not any((ROOT / "programs").glob("*/knowledge")):
        errors.append(
            "top-level knowledge/ found but no programs/*/knowledge — "
            "packs should live under programs/{slug}/"
        )

    return errors


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

    preflight_errors = _preflight()
    if preflight_errors:
        print("Repo is not ready to start the stack:", file=sys.stderr)
        for err in preflight_errors:
            print(f"  • {err}", file=sys.stderr)
        print(
            "\nPolicy packs live under programs/{slug}/ (rules + knowledge). "
            "The agent image COPYs programs/ — not a top-level knowledge/ directory.",
            file=sys.stderr,
        )
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
        explicit_client = os.environ.get("REDIS_URL", "").strip()
        agent_redis = _docker_reachable_url(explicit_client or public_redis)

    # Optional external Qdrant. If unset, spawn embedded Qdrant.
    external_qdrant = (
        os.environ.get("QDRANT_URL", "").strip() or os.environ.get("PUBLIC_QDRANT_URL", "").strip()
    )
    spawn_qdrant = not bool(external_qdrant)

    if spawn_qdrant:
        qdrant_port = _resolve_port("QDRANT_PORT", taken)
        public_qdrant = (
            os.environ.get("PUBLIC_QDRANT_URL", "").strip() or f"http://localhost:{qdrant_port}"
        )
        agent_qdrant = "http://qdrant:6333"
    else:
        qdrant_port = 0
        public_qdrant = os.environ.get("PUBLIC_QDRANT_URL", "").strip() or external_qdrant
        explicit_q = os.environ.get("QDRANT_URL", "").strip()
        agent_qdrant = _docker_reachable_url(explicit_q or public_qdrant, default_scheme_port=6333)

    public_base = os.environ.get("PUBLIC_BASE_URL", "").strip() or f"http://localhost:{agent_port}"
    embed_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "").strip() or "text-embedding-3-small"

    env = os.environ.copy()
    env["AGENT_PORT"] = str(agent_port)
    env["REDIS_PORT"] = str(redis_port if redis_port else 0)
    env["QDRANT_PORT"] = str(qdrant_port if qdrant_port else 0)
    env["PUBLIC_BASE_URL"] = public_base
    env["PUBLIC_REDIS_URL"] = public_redis
    env["REDIS_URL"] = agent_redis
    env["PUBLIC_QDRANT_URL"] = public_qdrant
    env["QDRANT_URL"] = agent_qdrant
    env["OPENAI_EMBEDDING_MODEL"] = embed_model

    compose_args = argv[1:] if argv[1:] else ["up", "--build"]
    if compose_args and compose_args[0].startswith("-"):
        compose_args = ["up", "--build", *compose_args]

    # Foreground `up` keeps streaming logs while ANY service runs. When the agent
    # exits (e.g. OpenAI quota), Redis/Qdrant would otherwise leave `make` hanging.
    # Abort the whole stack and return the agent's exit code so Make finishes.
    detached = "-d" in compose_args or "--detach" in compose_args
    if (
        compose_args
        and compose_args[0] == "up"
        and not detached
        and "--abort-on-container-exit" not in compose_args
    ):
        compose_args = [
            "up",
            "--abort-on-container-exit",
            "--exit-code-from",
            "agent",
            *compose_args[1:],
        ]

    pack_names = sorted(
        p.name
        for p in (ROOT / "programs").iterdir()
        if p.is_dir() and (p / "program.yaml").is_file()
    )

    print("Starting stack with Docker Compose…")
    print()
    print("Host ports / resources")
    print(f"  API health    {public_base}/api/health")
    print(f"  OpenAPI docs  {public_base}/docs")
    print(f"  Programs API  GET {public_base}/api/programs")
    print(f"  Chat API      POST {public_base}/api/chat")
    print(f"  Agent port    {agent_port}  (set AGENT_PORT to pin)")
    print(f"  Packs         {', '.join(pack_names) or '(none)'}")
    if spawn_redis:
        print(f"  Redis         {public_redis}  (embedded; set REDIS_PORT to pin)")
        print("  Redis mode    spawned by Compose (profile: embedded-redis)")
    else:
        print(f"  Redis         {public_redis}  (external; not spawned)")
        print(f"  Redis (agent) {agent_redis}")
    print("  Redis creds   (none assumed — configure auth on external Redis if needed)")
    if spawn_qdrant:
        print(f"  Qdrant        {public_qdrant}  (embedded; set QDRANT_PORT to pin)")
        print("  Qdrant mode   spawned by Compose (profile: embedded-qdrant)")
    else:
        print(f"  Qdrant        {public_qdrant}  (external; not spawned)")
        print(f"  Qdrant (agent) {agent_qdrant}")
    print(f"  Embeddings    {embed_model}  (same OPENAI_API_KEY as chat)")
    print("  CLI           make cli  (pick program; uses PUBLIC_BASE_URL)")
    print("  Smoke         make smoke PROGRAM=<slug>")
    if not detached and compose_args[0] == "up":
        print("  Foreground    aborts when agent exits (Make returns to the shell)")
    print()

    runtime = ROOT / ".env.runtime"
    runtime_lines = [
        f"AGENT_PORT={agent_port}",
        f"REDIS_PORT={redis_port}",
        f"QDRANT_PORT={qdrant_port}",
        f"PUBLIC_BASE_URL={public_base}",
        f"PUBLIC_REDIS_URL={public_redis}",
        f"REDIS_URL={agent_redis}",
        f"PUBLIC_QDRANT_URL={public_qdrant}",
        f"QDRANT_URL={agent_qdrant}",
        f"OPENAI_EMBEDDING_MODEL={embed_model}",
        f"EMBEDDED_REDIS={'1' if spawn_redis else '0'}",
        f"EMBEDDED_QDRANT={'1' if spawn_qdrant else '0'}",
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
    if spawn_qdrant:
        cmd.extend(["--profile", "embedded-qdrant"])
    cmd.extend(compose_args)
    return subprocess.call(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
