.PHONY: help install test lint typecheck clean build run dry-run test-all

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install all dependencies including dev
	pip install -e ".[dev]"

test:  ## Run unit tests
	pytest tests/unit -v --tb=short

test-integration:  ## Run integration tests
	pytest tests/integration -v --tb=short

test-all:  ## Run all tests with coverage
	pytest tests/ -v --tb=short --cov --cov-report=term-missing

lint:  ## Run ruff linter
	ruff check .

format:  ## Run ruff formatter
	ruff format .

typecheck:  ## Run mypy type checking
	mypy orchestrator/ agents/ integrations/ runners/ schemas/

clean:  ## Remove build artifacts and cache
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache __pycache__ data/executions/*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

build:  ## Build Docker image
	docker compose build

run:  ## Run in dry-run mode with sample task
	python -m orchestrator.engine --task examples/local-task.yaml --mode dry_run

run-local:  ## Run from a local task file
	python -m orchestrator.engine --task $(TASK) --mode $(MODE)