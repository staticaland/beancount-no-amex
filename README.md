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
uv add beancount fava

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
from beancount_no_amex import AmexAccountConfig, Importer, match, when, amount


def get_importers():
    return [
        Importer(AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            # Optional: specify account_id to match a specific card
            # account_id="XYZ|12345",
            transaction_patterns=[
                # Simple substring match
                match("SPOTIFY") >> "Expenses:Subscriptions:Music",
                match("NETFLIX") >> "Expenses:Subscriptions:Streaming",

                # Case-insensitive matching
                match("starbucks").ignorecase >> "Expenses:Coffee",

                # Regex pattern (handles variations like "REMA 1000", "REMA1000")
                match(r"REMA\s*1000").regex.ignorecase >> "Expenses:Groceries",

                # Amount-based rules
                when(amount < 50) >> "Expenses:PettyCash",
                when(amount.between(50, 200)) >> "Expenses:Shopping:Medium",

                # Combined: merchant + amount threshold
                match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol:Expensive",

                # More examples
                match("GITHUB") >> "Expenses:Cloud:GitHub",
                match("AWS") >> "Expenses:Cloud:AWS",
                match("COOP") >> "Expenses:Groceries",
                match("KIWI") >> "Expenses:Groceries",
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

## Classification for Humans

The library provides a Pythonic, fluent API for transaction classification:

```python
from beancount_no_amex import match, when, field, shared, amount

rules = [
    # Simple substring matching
    match("SPOTIFY") >> "Expenses:Music",
    match("NETFLIX") >> "Expenses:Entertainment",

    # Regex patterns
    match(r"REMA\s*1000").regex >> "Expenses:Groceries",

    # Case-insensitive matching
    match("starbucks").ignorecase >> "Expenses:Coffee",
    match("starbucks").i >> "Expenses:Coffee",  # short form

    # Amount-based rules
    when(amount < 50) >> "Expenses:PettyCash",
    when(amount > 1000) >> "Expenses:Large",
    when(amount.between(100, 500)) >> "Expenses:Medium",

    # Combined conditions
    match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol:Fine",

    # Field-based matching (for bank account numbers, transaction types, etc.)
    field(to_account="98712345678") >> "Assets:Savings",
    field(merchant_code=r"5411|5412").regex >> "Expenses:Groceries",

    # Split across multiple accounts
    match("COSTCO") >> [
        ("Expenses:Groceries", 80),
        ("Expenses:Household", 20),
    ],

    # Shared expenses (tracking what roommates owe you)
    match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50),
]
```

### API Reference

| Pattern Type | Example | Description |
|--------------|---------|-------------|
| Substring | `match("SPOTIFY") >> "..."` | Matches if narration contains "SPOTIFY" |
| Regex | `match(r"REMA\s*1000").regex >> "..."` | Regex pattern matching |
| Case-insensitive | `match("spotify").ignorecase >> "..."` | Case-insensitive match |
| Amount less than | `when(amount < 50) >> "..."` | Amount under threshold |
| Amount greater than | `when(amount > 500) >> "..."` | Amount over threshold |
| Amount range | `when(amount.between(100, 500)) >> "..."` | Amount within range |
| Combined | `match("STORE").where(amount > 100) >> "..."` | Narration + amount condition |
| Field match | `field(type="ATM") >> "..."` | Match on metadata fields |
| Split | `match("X") >> [("A", 80), ("B", 20)]` | Split across accounts |
| Shared | `... >> "X" \| shared("Receivable", 50)` | Track shared expenses |

### Traditional API

The fluent API builds on top of `TransactionPattern`, which you can still use directly:

```python
from beancount_no_amex import TransactionPattern, amount

patterns = [
    TransactionPattern(narration="SPOTIFY", account="Expenses:Music"),
    TransactionPattern(narration=r"REMA\s*1000", regex=True, account="Expenses:Groceries"),
    TransactionPattern(amount_condition=amount < 50, account="Expenses:PettyCash"),
]
```

## Features

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
