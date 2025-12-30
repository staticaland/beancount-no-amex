# beancount-no-amex

A Python library for importing American Express (Amex) (Norway) bank data into Beancount accounting format.

![amex2](https://github.com/user-attachments/assets/0d66903c-28a3-4953-9783-9c83362bb822)

## Quickstart

Get from zero to viewing your Amex transactions in Fava in under 5 minutes.

### 1. Create a new project

```bash
mkdir finances && cd finances
uv init
```

### 2. Add dependencies

```bash
# Add core dependencies
uv add "beancount>=3.1.0" fava

# Add git-based dependencies
uv add beangulp --git https://github.com/beancount/beangulp
uv add beancount-no-amex --git https://github.com/staticaland/beancount-no-amex
```

### 3. Configure as a package (manual edit needed)

Add the following to your `pyproject.toml`:

```toml
[tool.uv]
package = true

[project.scripts]
import-transactions = "finances.importers:main"
```

This enables the `import-transactions` command and makes your project installable.

Then sync to apply the changes:

```bash
uv sync
```

### 4. Create the importer

Create `src/finances/importers.py`:

```python
from beangulp import Ingest
from beancount_no_amex import AmexAccountConfig, Importer, TransactionPattern, amount


def get_importers():
    return [
        Importer(AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            # Optional: specify account_id to match a specific card
            # account_id="XYZ|12345",
            transaction_patterns=[
                # Simple substring match
                TransactionPattern(
                    narration="SPOTIFY",
                    account="Expenses:Subscriptions:Music",
                ),
                # Case-insensitive match
                TransactionPattern(
                    narration="netflix",
                    case_insensitive=True,
                    account="Expenses:Subscriptions:Streaming",
                ),
                # Regex pattern (handles variations like "REMA 1000", "REMA1000")
                TransactionPattern(
                    narration=r"REMA\s*1000",
                    regex=True,
                    case_insensitive=True,
                    account="Expenses:Groceries",
                ),
                # Amount-only condition (small purchases)
                TransactionPattern(
                    amount_condition=amount < 50,
                    account="Expenses:PettyCash",
                ),
                # Amount range
                TransactionPattern(
                    amount_condition=amount.between(50, 200),
                    account="Expenses:Shopping:Medium",
                ),
                # Combined: merchant + amount threshold
                TransactionPattern(
                    narration="VINMONOPOLET",
                    amount_condition=amount > 500,
                    account="Expenses:Alcohol:Expensive",
                ),
                # More examples
                TransactionPattern(narration="GITHUB", account="Expenses:Cloud:GitHub"),
                TransactionPattern(narration="AWS", account="Expenses:Cloud:AWS"),
                TransactionPattern(narration="COOP", account="Expenses:Groceries"),
                TransactionPattern(narration="KIWI", account="Expenses:Groceries"),
            ],
        )),
    ]


def main():
    ingest = Ingest(get_importers())
    ingest.main()


if __name__ == "__main__":
    main()
```

Also create `src/finances/__init__.py`:

```bash
mkdir -p src/finances
touch src/finances/__init__.py
```

### 5. Create the main ledger file

Create `main.beancount`:

```beancount
option "title" "My Finances"
option "operating_currency" "NOK"

; Account definitions
2020-01-01 open Liabilities:CreditCard:Amex NOK
2020-01-01 open Expenses:Subscriptions:Music NOK
2020-01-01 open Expenses:Subscriptions:Streaming NOK
2020-01-01 open Expenses:Groceries NOK
2020-01-01 open Expenses:PettyCash NOK
2020-01-01 open Expenses:Shopping:Medium NOK
2020-01-01 open Expenses:Alcohol:Expensive NOK
2020-01-01 open Expenses:Cloud:GitHub NOK
2020-01-01 open Expenses:Cloud:AWS NOK
2020-01-01 open Expenses:Uncategorized NOK

; Include imported transactions
include "imports/*.beancount"
```

Create the imports directory:

```bash
mkdir -p imports
```

### 6. Download your Amex statement

1. Log in to your American Express account
2. Go to Statements & Activity
3. Download the QBO file (should be named like `activity*.qbo`)
4. Place it in a `downloads/` folder

### 7. Import transactions

```bash
# Preview what will be imported
uv run import-transactions extract downloads/

# Save to a file
uv run import-transactions extract downloads/ > imports/2024-amex.beancount
```

### 8. View in Fava

```bash
uv run fava main.beancount
```

Open http://localhost:5000 in your browser.

## Features

### Transaction Pattern Matching

Patterns are evaluated in order - the first match wins:

| Feature | Example |
|---------|---------|
| Substring | `TransactionPattern(narration="SPOTIFY", account="...")` |
| Case-insensitive | `TransactionPattern(narration="netflix", case_insensitive=True, account="...")` |
| Regex | `TransactionPattern(narration=r"REMA\s*1000", regex=True, account="...")` |
| Amount less than | `TransactionPattern(amount_condition=amount < 50, account="...")` |
| Amount greater than | `TransactionPattern(amount_condition=amount > 500, account="...")` |
| Amount range | `TransactionPattern(amount_condition=amount.between(100, 500), account="...")` |
| Combined | `TransactionPattern(narration="STORE", amount_condition=amount > 100, account="...")` |

### Multiple Cards

Configure separate importers for different Amex cards:

```python
def get_importers():
    return [
        Importer(AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex:Personal",
            currency="NOK",
            account_id="XYZ|12345",  # From your QBO file
            transaction_patterns=[...],
        )),
        Importer(AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex:Business",
            currency="NOK",
            account_id="XYZ|67890",
            transaction_patterns=[...],
        )),
    ]
```

### Deduplication

Transactions are automatically deduplicated using FITID (Financial Transaction ID). Re-running the import won't create duplicates. To force re-import:

```python
AmexAccountConfig(
    account_name="...",
    currency="NOK",
    skip_deduplication=True,  # Bypass FITID checking
)
```

## Project Structure

After setup, your project should look like:

```
finances/
├── pyproject.toml
├── main.beancount
├── imports/
│   └── 2024-amex.beancount
├── downloads/
│   └── activity2024.qbo
└── src/
    └── finances/
        ├── __init__.py
        └── importers.py
```
