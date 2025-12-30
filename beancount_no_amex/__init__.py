from .credit import AmexAccountConfig, Importer  # NOQA
from .models import (
    AmountCondition,
    AmountOperator,
    BeanTransaction,
    ParsedTransaction,
    QboFileData,
    RawTransaction,
    TransactionPattern,
    amount,  # Proxy for natural comparison syntax
)

__all__ = [
    # Main classes
    "AmexAccountConfig",
    "Importer",
    # Pattern matching
    "AmountCondition",
    "AmountOperator",
    "TransactionPattern",
    "amount",  # Use: amount < 50, amount > 100, amount.between(50, 100)
    # Data models
    "BeanTransaction",
    "ParsedTransaction",
    "QboFileData",
    "RawTransaction",
]
