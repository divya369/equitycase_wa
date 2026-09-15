ifneq (,$(wildcard .env))
include .env
export
else
$(error .env file not found. Create it from .env.example)
endif

.PHONY: dev start


dev:
	uv run uvicorn src.main:app --reload --host $(APP_HOST) --port $(APP_PORT)

start:
	uv run uvicorn src.main:app --host $(APP_HOST) --port $(APP_PORT) 