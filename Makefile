# Public benefits eligibility agent
#   make dev              → install host deps + start API/Redis/Qdrant (Compose)
#   make smoke PROGRAM=…  → live multi-scenario E2E (PROGRAM required)
#
# Other targets: install | up | up-d | down | cli | index | test | hooks | lint

.PHONY: dev install up up-d down cli smoke index test hooks lint docker-check

POETRY ?= poetry
export POETRY_VIRTUALENVS_IN_PROJECT := true

# Host Python deps only (no Docker). Safe for test/lint on machines without Docker.
install:
	@command -v $(POETRY) >/dev/null 2>&1 || { \
		echo "Poetry is required. Install: https://python-poetry.org/docs/#installation"; \
		exit 1; \
	}
	$(POETRY) install --with dev
	@echo "==> Python deps ready (poetry env in .venv)."

docker-check:
	@command -v docker >/dev/null 2>&1 || { \
		echo "Docker is required for 'make dev' / 'make up'."; \
		exit 1; \
	}
	@docker compose version >/dev/null 2>&1 || { \
		echo "Docker Compose v2 is required (\`docker compose\`)."; \
		exit 1; \
	}

# Default: install host deps, then run the full stack (Compose + optional Redis/Qdrant).
dev: install docker-check
	@echo ""
	@echo "==> Starting stack (Docker Compose via start.py)…"
	@echo "    Set OPENAI_API_KEY in .env first if you have not already."
	@echo "    Program packs are under programs/{slug}/ (not top-level knowledge/)."
	@echo ""
	$(POETRY) run python start.py

# Start stack only (assumes install already ran).
up: docker-check
	$(POETRY) run python start.py

up-d: docker-check
	$(POETRY) run python start.py -d

down:
	@if [ -f .env.runtime ]; then \
		docker compose --env-file .env.runtime --profile embedded-redis --profile embedded-qdrant down; \
	else \
		docker compose --profile embedded-redis --profile embedded-qdrant down 2>/dev/null \
			|| docker compose down; \
	fi

# Interactive CLI talks to the agent HTTP API (PUBLIC_BASE_URL from .env.runtime).
cli: install
	@echo "==> CLI → agent API (PUBLIC_BASE_URL from .env.runtime)…"
	@echo "    Pick a program interactively, or: poetry run python -m src.cli --program nc-fns"
	$(POETRY) run python -m src.cli

# Live E2E via agent API (stack must be up). PROGRAM is required (no default).
#   make smoke PROGRAM=nc-fns
#   make smoke PROGRAM=ca-calfresh
smoke: install
	@if [ -z "$(PROGRAM)" ]; then echo "FAIL: set PROGRAM=<slug> (e.g. make smoke PROGRAM=nc-fns)"; exit 1; fi
	@echo "==> Smoke (multi-scenario) via agent API program=$(PROGRAM)…"
	$(POETRY) run python -m src.smoke --program $(PROGRAM)

# Re-sync knowledge embeddings into Qdrant (all packs; unchanged docs skipped).
index: install
	@echo "==> Syncing knowledge index → Qdrant (all programs/* packs)…"
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
