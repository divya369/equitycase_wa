ifneq (,$(wildcard .env))
include .env
export
else
$(error .env file not found. Create it from .env.example)
endif

.PHONY: dev


dev:
	uv run uvicorn src.main:app --reload --host $(APP_HOST) --port $(APP_PORT)