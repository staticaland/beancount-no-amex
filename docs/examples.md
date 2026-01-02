# Example Usage

This file contains examples that are automatically tested by Sybil.

## Basic Usage

You can work with transaction patterns:

```python
>>> from beancount_classifier import TransactionPattern, amount

>>> pattern = TransactionPattern(narration="VINMONOPOLET", account="Expenses:Groceries")
>>> pattern.account
'Expenses:Groceries'

```

## Amount Conditions

Amount conditions help match transactions by value:

```python
>>> from beancount_classifier import amount

>>> condition = amount < 50
>>> condition.value
Decimal('50')

>>> condition = amount > 100
>>> condition.value
Decimal('100')

```

## Simple Math (Sanity Check)

Just a simple sanity check that the doctest parsing works:

```python
>>> 1 + 1
2

>>> "hello".upper()
'HELLO'

```
