.PHONY: install dev test lint format up down send-voice send-chat

install:
	uv sync --all-groups

dev:
	uv run uvicorn webhook_relay.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest -q --cov=src --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check . --fix

up:
	docker compose up --build -d

down:
	docker compose down -v

send-voice:
	uv run python scripts/send_test_webhook.py --provider voice

send-chat:
	uv run python scripts/send_test_webhook.py --provider chat
