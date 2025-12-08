# Literate Programming with Beancount

This directory contains an example of using [Org mode](https://orgmode.org/) for literate programming with [Beancount](https://beancount.github.io/).

## Files

| File                  | Description                                      |
|-----------------------|--------------------------------------------------|
| `finance.org`         | Main literate document with queries and analysis |
| `accounts.beancount`  | Chart of accounts definitions                    |
| `2024.beancount`      | Sample transactions for 2024                     |

## Usage

### With Emacs

1. Open `finance.org` in Emacs with Org mode
2. Place cursor on any code block
3. Press `C-c C-c` to execute the query
4. Results appear inline below the code block

### From Command Line

You can also run queries directly:

```bash
# Check ledger validity
bean-check 2024.beancount

# Run a query
bean-query 2024.beancount "SELECT account, sum(position) WHERE account ~ 'Expenses' GROUP BY account"

# Generate reports
bean-report 2024.beancount balsheet
```

## Prerequisites

- [Beancount](https://beancount.github.io/) 3.x
- [Beanquery](https://github.com/beancount/beanquery) for bean-query
- Emacs with Org mode (for literate programming features)

Install with:

```bash
pip install beancount beanquery
```

## Why Literate Programming?

Combining documentation with executable queries provides:

- **Living documentation**: Queries stay up-to-date with your data
- **Reproducibility**: Anyone can re-run your analysis
- **Organization**: Related analyses grouped together
- **Version control**: Track changes to both data and analysis
