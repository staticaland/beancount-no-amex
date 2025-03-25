# Justfile for ruff linting and formatting

path := "beancount_no_amex"

# Default recipe to run when just is called without arguments
default:
    @just --list

# Lint all files in the specified directory (and any subdirectories)
check:
    ruff check {{path}}

test:
    uv run beancount-no-amex test test_data

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
