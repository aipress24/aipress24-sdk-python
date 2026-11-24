# The spec is committed in the application repository.
SPEC ?= ../aipress24/sdk/python/openapi.json

.PHONY: check test lint generate

check: lint test

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check

generate:
	cp $(SPEC) openapi.json
	uv run python generate.py openapi.json
	uv run ruff format aipress24_client/_generated.py
