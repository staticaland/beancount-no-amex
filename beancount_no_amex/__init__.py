from .credit import AmexAccountConfig, Importer  # noqa: F401

# Classification components (generic, reusable across importers)
from .classify import (
    AccountSplit,
    AmountCondition,
    AmountOperator,
    ClassifierMixin,
    TransactionClassifier,
    TransactionPattern,
    amount,  # Proxy for natural comparison syntax
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
    # Classification (generic, reusable)
    "AccountSplit",
    "AmountCondition",
    "AmountOperator",
    "ClassifierMixin",
    "TransactionClassifier",
    "TransactionPattern",
    "amount",  # Use: amount < 50, amount > 100, amount.between(50, 100)
    # OFX data models
    "BeanTransaction",
    "ParsedTransaction",
    "QboFileData",
    "RawTransaction",
]
