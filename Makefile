ifneq (,$(wildcard .env))
include .env
export
else
$(error .env file not found. Create it from .env.example)
endif

.PHONY: dev start


dev:
	uv run uvicorn main:app --app-dir src --reload --host $(APP_HOST) --port $(APP_PORT)

start:
	uv run uvicorn main:app --app-dir src --host $(APP_HOST) --port $(APP_PORT)

lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest