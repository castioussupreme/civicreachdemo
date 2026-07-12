# pnpm-dev equivalent for this stack:
#   make dev    → install deps + start API/Redis (Docker Compose)
#
# Other targets: install | up | down | cli | smoke | test | hooks | lint

.PHONY: dev install up up-d down cli smoke test hooks lint

POETRY ?= poetry
export POETRY_VIRTUALENVS_IN_PROJECT := true

# Default: install everything, then run the full stack (Compose + optional Redis).
dev: install
	@echo ""
	@echo "==> Starting stack (Docker Compose via start.py)…"
	@echo "    Set OPENAI_API_KEY in .env first if you have not already."
	@echo ""
	$(POETRY) run python start.py

# Install host Python deps (CLI, tests, hooks). Docker image installs its own.
install:
	@command -v $(POETRY) >/dev/null 2>&1 || { \
		echo "Poetry is required. Install: https://python-poetry.org/docs/#installation"; \
		exit 1; \
	}
	@command -v docker >/dev/null 2>&1 || { \
		echo "Docker is required for 'make dev' / 'make up'."; \
		exit 1; \
	}
	$(POETRY) install --with dev
	@echo "==> Python deps ready (poetry env in .venv)."

# Start stack only (assumes install already ran).
up:
	$(POETRY) run python start.py

up-d:
	$(POETRY) run python start.py -d

down:
	@if [ -f .env.runtime ]; then \
		docker compose --env-file .env.runtime down; \
	else \
		docker compose down; \
	fi

# Interactive CLI (needs Redis from 'make dev' / 'make up' in another terminal).
cli: install
	@echo "==> Connecting CLI to Redis (host URL from .env.runtime / PUBLIC_REDIS_URL)…"
	$(POETRY) run python -m src.cli

# Live E2E: real OpenAI + Redis + scripts/happy_path.txt (stack must be up).
smoke: install
	@echo "==> Smoke test (OPENAI_API_KEY + Redis required)…"
	$(POETRY) run python -m src.smoke

test: install
	$(POETRY) run pytest -q

hooks: install
	$(POETRY) run pre-commit install
	@echo "==> pre-commit hooks installed."
	@echo "    Run all checks:  poetry run pre-commit run --all-files"

lint: install
	$(POETRY) run ruff check src tests
	$(POETRY) run mypy --config-file=pyproject.toml
	$(POETRY) run vulture src tests --min-confidence 80
