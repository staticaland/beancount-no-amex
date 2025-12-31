# Agent Guidelines

Guidelines for AI agents working on this codebase.

## Using uv Properly

### Running Tests

**Wrong approaches tried:**

```bash
# Won't work - pytest not in system Python
python -m pytest

# Creates venv but doesn't install dev dependencies by default
uv run pytest

# Installs to wrong place or doesn't integrate with uv's venv properly
uv pip install pytest
```

**Correct approach:**

```bash
# Install all dependencies including dev group, then run
uv sync --group dev
uv run pytest
```

Or in one command:

```bash
uv run --group dev pytest
```

### Key uv Concepts

1. **`uv sync`** - Installs dependencies from pyproject.toml into `.venv`
2. **`uv sync --group dev`** - Also installs optional dev dependencies
3. **`uv run <cmd>`** - Runs command in the uv-managed environment
4. **`uv run --group dev <cmd>`** - Ensures dev deps are installed before running

### Common Pitfalls

- **Don't use `uv pip install`** for project dependencies - it bypasses uv's lockfile
- **Don't assume dev dependencies are installed** - they require explicit `--group dev`
- **Output ordering can be confusing** - uv may show install progress after error messages from a failed first attempt

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
| `classify.py` | `TransactionPattern`, `AmountCondition`, `ClassifierMixin` | Only beancount, pydantic |
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

Both work from the top-level package for convenience:
```python
from beancount_no_amex import TransactionPattern, amount, Importer
```

## Testing

Always run full test suite after refactoring:

```bash
uv run --group dev pytest -v
```

Current test count: 160 tests across:
- `test_currency.py` - Currency handling
- `test_deduplication.py` - FITID deduplication
- `test_extract.py` - Full extraction pipeline
- `test_finalize.py` - Transaction categorization
- `test_identify.py` - File identification
- `test_models.py` - Data model validation
- `test_parsing.py` - OFX parsing
- `test_pattern_matching.py` - Pattern matching logic

## Refactoring Checklist

When extracting code into new modules:

1. [ ] Create new module with clear docstring explaining purpose
2. [ ] Move code, keeping public API stable
3. [ ] Add re-exports in original location for backwards compatibility
4. [ ] Update `__init__.py` to export from new location
5. [ ] Run full test suite: `uv run --group dev pytest -v`
6. [ ] Verify all 160 tests pass before committing
