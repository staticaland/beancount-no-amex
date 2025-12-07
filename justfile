# Justfile for ruff linting and formatting

path := "beancount_no_amex"

# Default recipe to run when just is called without arguments
default:
    @just --list

# Lint all files in the specified directory (and any subdirectories)
check:
    ruff check {{path}}

# Run beangulp integration tests (compares output against .beancount files)
test-beangulp:
    uv run beancount-no-amex test test_data

# Run pytest unit and component tests
test:
    uv run --extra dev pytest tests/ -v

# Run pytest with coverage report
test-cov:
    uv run --extra dev pytest tests/ -v --cov=beancount_no_amex --cov-report=term-missing

# Run all tests (pytest + beangulp)
test-all: test test-beangulp

# Format all files in the specified directory (and any subdirectories)
format:
    ruff format {{path}}

# Lint and fix issues automatically where possible
fix:
    ruff check --fix {{path}}

isort:
    ruff check --select I --fix

# Show all warnings, even ones that are ignored by default
check-all:
    ruff check --select ALL {{path}}

# Runs both check and format
all: check isort format
    @echo "Both check and format completed"

# Display ruff version
version:
    ruff --version
