.PHONY: install format lint typecheck test check run

install:
	uv sync --extra dev --extra data

format:
	uv run ruff format src tests

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src

test:
	uv run pytest

check:
	uv run ruff check src tests
	uv run mypy src
	uv run pytest

run:
	uv run uvicorn fund_manager.apps.api.main:app --reload
