# Agent Guidelines

Guidelines for AI agents working on this codebase.

## Using uv

### Setup and Testing

```bash
# Install all dependencies including dev tools
uv sync --extra dev

# Run tests
uv run pytest -v
```

### Running Commands

Always prefix commands with `uv run`:

```bash
uv run pytest
uv run python -c "import beancount_no_amex"
uv run beancount-no-amex extract file.qbo
```

### Adding Dependencies

```bash
# Add a runtime dependency
uv add <package>

# Add a dev dependency
uv add --optional dev <package>
```

## Project Structure

```
beancount_no_amex/
├── __init__.py      # Public API exports
├── classify.py      # Generic classification (reusable across importers)
├── credit.py        # OFX/Amex-specific importer
└── models.py        # OFX data models + backwards-compat re-exports
```

### Module Responsibilities

| Module | Contains | Depends On |
|--------|----------|------------|
| `classify.py` | `TransactionPattern`, `AmountCondition`, `ClassifierMixin` | beancount, pydantic |
| `models.py` | `RawTransaction`, `ParsedTransaction`, `QboFileData` | classify.py (re-exports) |
| `credit.py` | `Importer`, `AmexAccountConfig`, OFX parsing | classify.py, models.py, beangulp |

### Import Conventions

For classification (generic, reusable):
```python
from beancount_no_amex.classify import TransactionPattern, amount, ClassifierMixin
```

For OFX-specific types:
```python
from beancount_no_amex.models import RawTransaction, QboFileData
```

Top-level convenience imports:
```python
from beancount_no_amex import TransactionPattern, amount, Importer
```

## Testing

Run full test suite after changes:

```bash
uv sync --extra dev
uv run pytest -v
```

All 160 tests must pass before committing.

## Refactoring Checklist

When extracting code into new modules:

1. Create new module with clear docstring explaining purpose
2. Move code, keeping public API stable
3. Update `__init__.py` to export from new location
4. Update imports in tests to use new module paths
5. Run `uv sync --extra dev && uv run pytest -v`
6. Verify all tests pass before committing
