from .credit import AmexAccountConfig, Importer  # noqa: F401

# Classification components (generic, reusable across importers)
from .classify import (
    # Fluent API - "Classification for Humans"
    match,   # match("SPOTIFY") >> "Expenses:Music"
    when,    # when(amount < 50) >> "Expenses:PettyCash"
    field,   # field(to_account="12345") >> "Assets:Savings"
    shared,  # ... | shared("Assets:Receivables:Alex", 50)
    amount,  # amount < 50, amount > 100, amount.between(50, 100)
    # Core classes (advanced usage)
    AccountSplit,
    AmountCondition,
    AmountOperator,
    ClassificationResult,
    ClassifierMixin,
    SharedExpense,
    TransactionClassifier,
    TransactionPattern,
)

# OFX-specific data models
from .models import (
    BeanTransaction,
    ParsedTransaction,
    QboFileData,
    RawTransaction,
)

__all__ = [
    # Main importer classes
    "AmexAccountConfig",
    "Importer",
    # Fluent API - "Classification for Humans"
    "match",   # match("SPOTIFY") >> "Expenses:Music"
    "when",    # when(amount < 50) >> "Expenses:PettyCash"
    "field",   # field(to_account="12345") >> "Assets:Savings"
    "shared",  # ... | shared("Assets:Receivables:Alex", 50)
    "amount",  # amount < 50, amount > 100, amount.between(50, 100)
    # Classification (advanced usage)
    "AccountSplit",
    "AmountCondition",
    "AmountOperator",
    "ClassificationResult",
    "ClassifierMixin",
    "SharedExpense",
    "TransactionClassifier",
    "TransactionPattern",
    # OFX data models
    "BeanTransaction",
    "ParsedTransaction",
    "QboFileData",
    "RawTransaction",
]
