package_path := "src/beancount_no_amex"

default:
    @just --list

test:
    uv run pytest tests/ -v

test-cov:
    uv run pytest tests/ -v --cov=beancount_no_amex --cov-report=term-missing

lint:
    find src tests -name '*.py' -print | xargs uv run ruff check

typecheck:
    uv run mypy --no-incremental {{package_path}}

check: lint typecheck test

test-all: test

format:
    find src tests -name '*.py' -print | xargs uv run ruff format

fix:
    find src tests -name '*.py' -print | xargs uv run ruff check --fix

all: check

version:
    uv run ruff --version
