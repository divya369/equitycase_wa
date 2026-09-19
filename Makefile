ifneq (,$(wildcard .env))
include .env
else
$(error .env file not found. Create it from .env.example)
endif

# Bare imports (`from config...`) resolve against src/
export PYTHONPATH := src

UVICORN := uv run uvicorn main:app --app-dir src --host $(APP_HOST) --port $(APP_PORT) --workers 1

.PHONY: help up down down-v logs psql \
	migration migrate downgrade downgrade-base history current \
	seed dev start webhook-sample lint format check test

help:
	@echo "Docker:     up | down | down-v | logs | psql"
	@echo "Migrations: migration m=\"message\" | migrate | downgrade | downgrade-base | history | current"
	@echo "App:        seed | dev | start | webhook-sample"
	@echo "Quality:    lint | format | check | test"

# ---------------------------------------------------------------------------
# Docker (Postgres)
# ---------------------------------------------------------------------------
up:
	docker compose up -d --wait

down:
	docker compose down

# Stop and DELETE the database volume
down-v:
	docker compose down -v

logs:
	docker compose logs -f postgres

psql:
	docker compose exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# ---------------------------------------------------------------------------
# Migrations (Alembic)
# ---------------------------------------------------------------------------
migration:
ifndef m
	$(error Usage: make migration m="describe the change")
endif
	uv run alembic revision --autogenerate -m "$(m)"

migrate:
	uv run alembic upgrade head

downgrade:
	uv run alembic downgrade -1

downgrade-base:
	uv run alembic downgrade base

history:
	uv run alembic history --verbose

current:
	uv run alembic current

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
seed:
	uv run python -m scripts.seed

# ws_manager is in-process memory: exactly ONE worker
dev:
	$(UVICORN) --reload --reload-dir src

start:
	$(UVICORN)

# Signed sample webhook body for api.rest -> .webhook/body.json
#   make webhook-sample [kind=status|message] [status=sent|delivered|read|failed]
#                       [wamid=...] [from=919...] [text="..."]
webhook-sample:
	uv run python -m scripts.webhook_sample --kind=$(kind) --status=$(status) \
		--wamid=$(wamid) --from=$(from) --text="$(text)"

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest
