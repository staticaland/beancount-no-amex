"""Generic transaction classification for Beancount importers.

This module provides reusable components for classifying and categorizing
transactions based on patterns. It can be used by any Beancount importer,
regardless of the source format (OFX, CSV, MT940, etc.).

Example usage:

    from beancount_no_amex.classify import (
        TransactionPattern,
        amount,
        ClassifierMixin,
    )

    # Define patterns
    patterns = [
        TransactionPattern(narration="SPOTIFY", account="Expenses:Subscriptions"),
        TransactionPattern(
            narration=r"REMA\\s*1000",
            regex=True,
            account="Expenses:Groceries"
        ),
        TransactionPattern(
            amount_condition=amount < 50,
            account="Expenses:PettyCash"
        ),
    ]

    # Use in your importer
    class MyImporter(ClassifierMixin, beangulp.Importer):
        def __init__(self, config):
            self.transaction_patterns = config.patterns
            # ... your importer setup
"""

from decimal import Decimal
from enum import Enum
from functools import cached_property
import re
from typing import Any

from beancount.core import data
from beancount.core.amount import Amount
from pydantic import BaseModel, model_validator, field_validator


class AmountOperator(str, Enum):
    """Operators for amount-based matching."""
    LT = "lt"       # Less than
    LTE = "lte"     # Less than or equal
    GT = "gt"       # Greater than
    GTE = "gte"     # Greater than or equal
    EQ = "eq"       # Equal
    BETWEEN = "between"  # Between two values (inclusive)


# Type alias for amount values that can be coerced to Decimal
AmountValue = Decimal | str | int | float


class AmountCondition(BaseModel):
    """Condition for matching transaction amounts.

    Examples:
        - AmountCondition(operator=AmountOperator.LT, value=Decimal("100"))
          Matches amounts less than 100
        - AmountCondition(operator=AmountOperator.BETWEEN, value=Decimal("50"), value2=Decimal("200"))
          Matches amounts between 50 and 200 (inclusive)

    Note: Matching is performed on the absolute value of the transaction amount,
    so you don't need to worry about signs (debits vs credits).
    """
    operator: AmountOperator
    value: Decimal
    value2: Decimal | None = None  # Only used for BETWEEN operator

    @field_validator('value', 'value2', mode='before')
    @classmethod
    def validate_amount(cls, v):
        """Ensure amount is a valid decimal."""
        if v is None:
            return None
        return Decimal(v) if isinstance(v, (str, int, float)) else v

    @model_validator(mode='after')
    def validate_between(self):
        """Ensure value2 is provided when operator is BETWEEN."""
        if self.operator == AmountOperator.BETWEEN and self.value2 is None:
            raise ValueError("value2 is required when operator is BETWEEN")
        return self

    def matches(self, amount: Decimal) -> bool:
        """Check if the given amount matches this condition.

        Args:
            amount: The transaction amount (sign is ignored, absolute value is used)

        Returns:
            True if the amount matches this condition
        """
        # Use absolute value for comparison - allows matching both debits and credits
        abs_amount = abs(amount)

        match self.operator:
            case AmountOperator.LT:
                return abs_amount < self.value
            case AmountOperator.LTE:
                return abs_amount <= self.value
            case AmountOperator.GT:
                return abs_amount > self.value
            case AmountOperator.GTE:
                return abs_amount >= self.value
            case AmountOperator.EQ:
                return abs_amount == self.value
            case AmountOperator.BETWEEN:
                return self.value <= abs_amount <= self.value2


class TransactionPattern(BaseModel):
    """Pattern for matching transactions based on narration and/or amount.

    A pattern matches a transaction if ALL specified conditions are met:
    - If narration is specified, it must match (substring or regex)
    - If amount_condition is specified, the amount must satisfy it

    At least one of narration or amount_condition must be specified.

    Examples:
        # Simple substring match
        TransactionPattern(narration="SPOTIFY", account="Expenses:Entertainment:Music")

        # Regex match for narration
        TransactionPattern(narration=r"REMA\\s*1000", regex=True, account="Expenses:Groceries")

        # Using the amount proxy for cleaner syntax
        TransactionPattern(amount_condition=amount < 50, account="Expenses:PettyCash")
        TransactionPattern(amount_condition=amount.between(100, 500), account="Expenses:Medium")

        # Combined: specific merchant with amount range
        TransactionPattern(
            narration="VINMONOPOLET",
            amount_condition=amount > 500,
            account="Expenses:Entertainment:Alcohol:Expensive"
        )
    """
    narration: str | None = None
    regex: bool = False  # If True, narration is treated as a regex pattern
    case_insensitive: bool = False  # If True, narration matching is case-insensitive
    amount_condition: AmountCondition | None = None
    account: str  # Target account to categorize to

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode='after')
    def validate_has_condition(self):
        """Ensure at least one matching condition is specified."""
        if self.narration is None and self.amount_condition is None:
            raise ValueError("At least one of narration or amount_condition must be specified")
        return self

    @cached_property
    def _compiled_pattern(self) -> re.Pattern | None:
        """Lazily compile and cache the regex pattern for narration matching."""
        if self.narration is None:
            return None

        flags = re.IGNORECASE if self.case_insensitive else 0
        if self.regex:
            return re.compile(self.narration, flags)
        # For non-regex, escape special characters for literal matching
        return re.compile(re.escape(self.narration), flags)

    def matches(self, narration: str, amount: Decimal) -> bool:
        """Check if a transaction matches this pattern.

        Args:
            narration: The transaction narration/description
            amount: The transaction amount

        Returns:
            True if the transaction matches all specified conditions
        """
        # Check narration condition
        if self.narration is not None:
            if self._compiled_pattern is None or self._compiled_pattern.search(narration) is None:
                return False

        # Check amount condition
        if self.amount_condition is not None and not self.amount_condition.matches(amount):
            return False

        return True


# =============================================================================
# Amount proxy for natural comparison syntax
# =============================================================================


class _AmountProxy:
    """Proxy object that captures comparison operators to build AmountCondition.

    This enables natural Python syntax for amount conditions:
        amount < 100      # Less than 100
        amount <= 100     # Less than or equal to 100
        amount > 500      # Greater than 500
        amount >= 500     # Greater than or equal to 500
        amount == 99      # Exactly 99
        amount.between(100, 500)  # Between 100 and 500 (inclusive)

    Example:
        from beancount_no_amex.classify import TransactionPattern, amount

        TransactionPattern(
            amount_condition=amount < 50,
            account="Expenses:PettyCash"
        )
    """

    def __lt__(self, other: AmountValue) -> AmountCondition:
        return AmountCondition(operator=AmountOperator.LT, value=Decimal(str(other)))

    def __le__(self, other: AmountValue) -> AmountCondition:
        return AmountCondition(operator=AmountOperator.LTE, value=Decimal(str(other)))

    def __gt__(self, other: AmountValue) -> AmountCondition:
        return AmountCondition(operator=AmountOperator.GT, value=Decimal(str(other)))

    def __ge__(self, other: AmountValue) -> AmountCondition:
        return AmountCondition(operator=AmountOperator.GTE, value=Decimal(str(other)))

    def __eq__(self, other: AmountValue) -> AmountCondition:  # type: ignore[override]
        return AmountCondition(operator=AmountOperator.EQ, value=Decimal(str(other)))

    def between(self, low: AmountValue, high: AmountValue) -> AmountCondition:
        """Create a 'between' condition (inclusive).

        Example:
            amount.between(100, 500)  # Matches 100, 250, 500, but not 99 or 501
        """
        return AmountCondition(
            operator=AmountOperator.BETWEEN,
            value=Decimal(str(low)),
            value2=Decimal(str(high)),
        )


# Singleton instance - import this for natural syntax
amount = _AmountProxy()


# =============================================================================
# Transaction Classifier
# =============================================================================


class TransactionClassifier:
    """Generic transaction classifier that matches patterns against transactions.

    This class can be used standalone or through the ClassifierMixin.

    Example:
        classifier = TransactionClassifier(patterns)
        account = classifier.classify("SPOTIFY PREMIUM", Decimal("-9.99"))
        if account:
            print(f"Matched: {account}")
    """

    def __init__(self, patterns: list[TransactionPattern]):
        """Initialize the classifier with a list of patterns.

        Args:
            patterns: List of TransactionPattern objects. Patterns are evaluated
                     in order; the first match wins.
        """
        self.patterns = patterns

    def classify(self, narration: str, amount: Decimal) -> str | None:
        """Find the matching account for a transaction.

        Args:
            narration: The transaction narration/description
            amount: The transaction amount

        Returns:
            The target account from the first matching pattern, or None if no match
        """
        for pattern in self.patterns:
            if pattern.matches(narration, amount):
                return pattern.account
        return None

    def add_balancing_posting(
        self,
        txn: data.Transaction,
        account: str,
    ) -> data.Transaction:
        """Add a balancing posting to a transaction.

        Creates a posting with the opposite amount to balance the transaction.

        Args:
            txn: The transaction to modify (must have at least one posting)
            account: The target account for the balancing posting

        Returns:
            A new transaction with the balancing posting added
        """
        if not txn.postings:
            return txn

        primary_posting = txn.postings[0]
        opposite_units = Amount(
            -primary_posting.units.number,
            primary_posting.units.currency
        )
        balancing_posting = data.Posting(
            account, opposite_units, None, None, None, None
        )
        return txn._replace(postings=txn.postings + [balancing_posting])


# =============================================================================
# Beangulp Importer Mixin
# =============================================================================


class ClassifierMixin:
    """Mixin that provides transaction classification for beangulp importers.

    Add this mixin to your importer class to get automatic transaction
    categorization based on patterns.

    Your importer class must have a `transaction_patterns` attribute
    (list of TransactionPattern objects).

    Example:
        class MyImporter(ClassifierMixin, beangulp.Importer):
            def __init__(self, config):
                self.transaction_patterns = config.transaction_patterns
                # ... rest of your setup

            def extract(self, filepath, existing):
                # Your extraction logic
                # finalize() is provided by the mixin
                ...
    """

    # This attribute should be set by the importer class
    transaction_patterns: list[TransactionPattern]

    def finalize(self, txn: data.Transaction, row: Any) -> data.Transaction | None:
        """Post-process the transaction with categorization based on patterns.

        This method is called by beangulp after extract() for each transaction.

        Args:
            txn: The transaction object to finalize
            row: The original source data (format-specific, passed through)

        Returns:
            The transaction with a balancing posting added if a pattern matched,
            or the original transaction unchanged if no match.
            Return None to skip/drop the transaction.
        """
        if not txn.postings or not self.transaction_patterns:
            return txn

        classifier = TransactionClassifier(self.transaction_patterns)
        narration = txn.narration or ""
        txn_amount = txn.postings[0].units.number

        if account := classifier.classify(narration, txn_amount):
            return classifier.add_balancing_posting(txn, account)

        return txn
