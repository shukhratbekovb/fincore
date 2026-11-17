.PHONY: dev serve infra infra-down infra-logs postgres redis worker worker-once cleanup cleanup-preview mailpit test test-unit test-integration test-cov
.DEFAULT_GOAL := dev

DEV_COMPOSE = docker compose --env-file .env -f ../compose.dev.yml
DEV_PORT ?= 8000

infra:
	$(DEV_COMPOSE) up -d --wait

infra-down:
	$(DEV_COMPOSE) down

infra-logs:
	$(DEV_COMPOSE) logs --tail=100 -f

dev:
	poetry run uvicorn backend.main:app --app-dir src --reload --no-proxy-headers --port $(DEV_PORT)

# Nginx and Uvicorn on the same host; see README for other topologies.
serve:
	poetry run uvicorn backend.main:app --app-dir src --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1

postgres:
	$(DEV_COMPOSE) up -d --wait postgres

redis:
	$(DEV_COMPOSE) up -d --wait redis

worker:
	PYTHONPATH=src poetry run python -m backend.bootstrap.outbox_worker

worker-once:
	PYTHONPATH=src poetry run python -m backend.bootstrap.outbox_worker --once

cleanup:
	PYTHONPATH=src poetry run python -m backend.bootstrap.cleanup

cleanup-preview:
	PYTHONPATH=src poetry run python -m backend.bootstrap.cleanup --dry-run

mailpit:
	$(DEV_COMPOSE) up -d --wait mailpit

test:
	poetry run pytest $(ARGS)

test-cov:
	poetry run pytest --cov --cov-report=term-missing --cov-report=html $(ARGS)

test-unit:
	poetry run pytest -m unit $(ARGS)

test-integration:
	poetry run pytest -m integration $(ARGS)
