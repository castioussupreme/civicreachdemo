# pnpm-dev equivalent for this stack:
#   make dev    → install deps + start API/Redis (Docker Compose)
#
# Other targets: install | up | down | cli | smoke | test | hooks | lint

.PHONY: dev install up up-d down cli smoke index test hooks lint

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

# Interactive CLI talks to the agent HTTP API (PUBLIC_BASE_URL from .env.runtime).
cli: install
	@echo "==> CLI → agent API (PUBLIC_BASE_URL from .env.runtime)…"
	$(POETRY) run python -m src.cli

# Live E2E via agent API + scripts/happy_path.txt (stack must be up).
smoke: install
	@echo "==> Smoke test via agent API (stack must be up)…"
	$(POETRY) run python -m src.smoke

# Re-sync knowledge embeddings into Qdrant (only changed docs re-embedded).
index: install
	@echo "==> Syncing knowledge index → Qdrant…"
	$(POETRY) run python -c "from src.retrieval.index import reset_index_flag, sync_knowledge_index; reset_index_flag(); r=sync_knowledge_index(); print(r)"

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
