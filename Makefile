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
	seed add-operator remove-operator dev start webhook-sample webhook-send \
	lint format check test

help:
	@echo "Docker:     up | down | down-v | logs | psql"
	@echo "Migrations: migration m=\"message\" | migrate | downgrade | downgrade-base | history | current"
	@echo "App:        seed | add-operator phone= name= | remove-operator phone= | dev | start"
	@echo "Webhook:    webhook-sample | webhook-send"
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

# Extra operators for the shared inbox (the seeded one comes from `make seed`)
#   make add-operator phone=+919820011223 name="Ananya"
#   make remove-operator phone=+919820011223
add-operator:
ifndef phone
	$(error Usage: make add-operator phone=+919820011223 name="Ananya")
endif
	uv run python -m scripts.add_operator "$(phone)" "$(or $(name),Operator)"

remove-operator:
ifndef phone
	$(error Usage: make remove-operator phone=+919820011223)
endif
	uv run python -m scripts.remove_operator "$(phone)"

# ws_manager is in-process memory: exactly ONE worker
dev:
	$(UVICORN) --reload --reload-dir src

start:
	$(UVICORN)

# Signed sample webhook body for api.rest -> .webhook/body.json
#   make webhook-sample [kind=status|message] [status=sent|delivered|read|failed]
#                       [wamid=...] [from=919...] [text="..."] [name="..."]
webhook-sample:
	uv run python -m scripts.webhook_sample --kind=$(kind) --status=$(status) \
		--wamid=$(wamid) --from=$(from) --text="$(text)" --name="$(name)"

# Same options, and POSTs the signed body to $(url) (default: local server)
webhook-send:
	uv run python -m scripts.webhook_sample --kind=$(kind) --status=$(status) \
		--wamid=$(wamid) --from=$(from) --text="$(text)" --name="$(name)" \
		--send=$(or $(url),http://127.0.0.1:8080)

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
