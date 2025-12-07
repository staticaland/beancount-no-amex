# beancount-no-amex

A Python library for importing American Express (Amex) (Norway) bank data into Beancount accounting format.

![amex2](https://github.com/user-attachments/assets/0d66903c-28a3-4953-9783-9c83362bb822)

## The Day-to-Day Workflow

Here's what using this tool actually looks like in practice:

### 1. Download Your Statement from AMEX

Log in to your American Express (Norway) account and download your statement as a QBO file. The file will be named something like `activity.qbo`.

```
~/Downloads/
└── activity.qbo    ← Fresh from AMEX
```

### 2. Run the Importer

Point the importer at your downloads directory:

```bash
uv run beancount-no-amex extract ~/Downloads/activity.qbo >> ledger.beancount
```

Or use beangulp's interactive mode to process multiple files:

```bash
uv run beancount-no-amex ~/Downloads/
```

### 3. What Comes Out

Your QBO file transforms into clean Beancount transactions:

```beancount
2025-03-15 * "VINMONOPOLET" "VINMONOPOLET MAJORSTUEN"
  id: "2025031512345678"
  type: "DEBIT"
  Liabilities:CreditCard:Amex  -299.00 NOK
  Expenses:Groceries            299.00 NOK

2025-03-16 * "SPOTIFY" "SPOTIFY AB"
  id: "2025031687654321"
  type: "DEBIT"
  Liabilities:CreditCard:Amex  -119.00 NOK
  Expenses:Entertainment:Music  119.00 NOK

2025-03-20 balance Liabilities:CreditCard:Amex  -418.00 NOK
```

The categorization (`Expenses:Groceries`, etc.) happens automatically based on patterns you configure.

### 4. What About Duplicates?

Each transaction from AMEX comes with a unique `FITID` (Financial Transaction ID), stored as the `id` metadata field. If you import the same statement twice, you'll see duplicates in your ledger.

**Current approach**: The `id` field is your friend here. You can grep for duplicate IDs:

```bash
grep "id:" ledger.beancount | sort | uniq -d
```

**Future**: Full duplicate detection using beangulp's built-in deduplication is planned but not yet implemented.

**Practical tip**: Keep your downloaded QBO files organized by month, and only import new ones:

```
~/finances/
├── amex/
│   ├── 2025-01-activity.qbo
│   ├── 2025-02-activity.qbo
│   └── 2025-03-activity.qbo  ← Import only this one
└── ledger.beancount
```

### 5. Multi-Card Setup

Have multiple AMEX cards? Configure separate importers for each:

```python
get_importers() → [
    Importer(AmexAccountConfig(
        account_name='Liabilities:CreditCard:Amex:Personal',
        currency='NOK',
        account_id='XYZ|12345',  # Matches only this card
        narration_to_account_mappings=[...],
    )),
    Importer(AmexAccountConfig(
        account_name='Liabilities:CreditCard:Amex:Business',
        currency='NOK',
        account_id='XYZ|67890',  # Matches the other card
        narration_to_account_mappings=[...],
    )),
]
```

The importer checks the account ID in each QBO file and routes it to the right configuration.

## The Pipeline

For a deep dive into how QBO files transform into Beancount directives, see [docs/README.md](docs/README.md).
