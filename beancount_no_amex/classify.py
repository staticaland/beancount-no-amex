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


class AccountSplit(BaseModel):
    """A single account with its percentage of the transaction.

    Used in TransactionPattern to split a transaction across multiple accounts.

    Example:
        AccountSplit(account="Expenses:Groceries", percentage=80)
        AccountSplit(account="Expenses:Household", percentage=20)

    Note: Percentages should be between 0 and 100 (not 0 and 1).
    """
    account: str
    percentage: Decimal

    @field_validator('percentage', mode='before')
    @classmethod
    def validate_percentage(cls, v):
        """Ensure percentage is a valid decimal between 0 and 100."""
        # Convert via string to preserve precision for floats
        val = Decimal(str(v)) if isinstance(v, (str, int, float)) else v
        if val < 0 or val > 100:
            raise ValueError("percentage must be between 0 and 100")
        return val


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
    Either account (single) or splits (multiple accounts) must be specified.

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

        # Split transaction across multiple accounts
        TransactionPattern(
            narration="COSTCO",
            splits=[
                AccountSplit(account="Expenses:Groceries", percentage=80),
                AccountSplit(account="Expenses:Household", percentage=20),
            ]
        )
    """
    narration: str | None = None
    regex: bool = False  # If True, narration is treated as a regex pattern
    case_insensitive: bool = False  # If True, narration matching is case-insensitive
    amount_condition: AmountCondition | None = None
    account: str | None = None  # Target account (single), mutually exclusive with splits
    splits: list[AccountSplit] | None = None  # Split across multiple accounts

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode='after')
    def validate_pattern(self):
        """Validate pattern configuration."""
        # Must have at least one matching condition
        if self.narration is None and self.amount_condition is None:
            raise ValueError("At least one of narration or amount_condition must be specified")

        # Must have exactly one of account or splits
        if self.account is None and self.splits is None:
            raise ValueError("Either account or splits must be specified")
        if self.account is not None and self.splits is not None:
            raise ValueError("Cannot specify both account and splits")

        # Validate splits percentages sum to <= 100
        if self.splits is not None:
            total = sum(s.percentage for s in self.splits)
            if total > 100:
                raise ValueError(f"Split percentages sum to {total}, must be <= 100")

        return self

    def get_splits(self) -> list[AccountSplit]:
        """Get the account splits for this pattern.

        Returns a list of AccountSplit objects. For single account patterns,
        returns a single split with 100% to that account.
        """
        if self.splits is not None:
            return self.splits
        # Single account = 100% to that account
        return [AccountSplit(account=self.account, percentage=Decimal("100"))]

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
        splits = classifier.classify("SPOTIFY PREMIUM", Decimal("-9.99"))
        if splits:
            for account, percentage in splits:
                print(f"  {percentage}% -> {account}")

        # With default account for unmatched transactions
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:Uncategorized"
        )

        # With default split percentage (for review workflow)
        # Matched transactions split between matched account and default
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("50")  # 50% confident
        )
    """

    def __init__(
        self,
        patterns: list[TransactionPattern],
        default_account: str | None = None,
        default_split_percentage: Decimal | None = None,
    ):
        """Initialize the classifier with patterns and optional defaults.

        Args:
            patterns: List of TransactionPattern objects. Patterns are evaluated
                     in order; the first match wins.
            default_account: Account for unmatched transactions. When set,
                           unmatched transactions go 100% to this account.
            default_split_percentage: When set (0-100), matched transactions are
                           split: (100 - this value)% to matched account(s),
                           this value % to default_account. Requires default_account.
                           Set to None to disable (default).
        """
        self.patterns = patterns
        self.default_account = default_account
        self.default_split_percentage = default_split_percentage

        # Validate: default_split_percentage requires default_account
        if default_split_percentage is not None and default_account is None:
            raise ValueError("default_split_percentage requires default_account to be set")

    def classify(self, narration: str, amount: Decimal) -> list[AccountSplit] | None:
        """Find the matching account(s) for a transaction.

        Args:
            narration: The transaction narration/description
            amount: The transaction amount

        Returns:
            A list of AccountSplit objects representing how to split the transaction,
            or None if no match and no default_account is configured.

            When default_split_percentage is set, matched transactions are split
            between the matched account(s) and default_account.
        """
        # Find matching pattern
        matched_pattern = None
        for pattern in self.patterns:
            if pattern.matches(narration, amount):
                matched_pattern = pattern
                break

        if matched_pattern is not None:
            # Get the pattern's splits
            splits = matched_pattern.get_splits()

            # Apply default_split_percentage if configured
            if self.default_split_percentage is not None:
                # Scale down the matched splits
                scale_factor = (Decimal("100") - self.default_split_percentage) / Decimal("100")
                scaled_splits = [
                    AccountSplit(
                        account=s.account,
                        percentage=s.percentage * scale_factor
                    )
                    for s in splits
                ]
                # Add remainder to default_account
                scaled_splits.append(AccountSplit(
                    account=self.default_account,
                    percentage=self.default_split_percentage
                ))
                return scaled_splits

            return splits

        # No match - use default_account if configured
        if self.default_account is not None:
            return [AccountSplit(account=self.default_account, percentage=Decimal("100"))]

        return None

    def add_balancing_posting(
        self,
        txn: data.Transaction,
        account: str,
    ) -> data.Transaction:
        """Add a balancing posting to a transaction (single account).

        Creates a posting with the opposite amount to balance the transaction.
        For backwards compatibility - prefer add_balancing_postings for splits.

        Args:
            txn: The transaction to modify (must have at least one posting)
            account: The target account for the balancing posting

        Returns:
            A new transaction with the balancing posting added
        """
        return self.add_balancing_postings(
            txn,
            [AccountSplit(account=account, percentage=Decimal("100"))]
        )

    def add_balancing_postings(
        self,
        txn: data.Transaction,
        splits: list[AccountSplit],
    ) -> data.Transaction:
        """Add balancing postings to a transaction based on splits.

        Creates postings with opposite amounts proportional to each split's
        percentage to balance the transaction.

        Args:
            txn: The transaction to modify (must have at least one posting)
            splits: List of AccountSplit objects defining how to split the balance

        Returns:
            A new transaction with the balancing postings added
        """
        if not txn.postings or not splits:
            return txn

        primary_posting = txn.postings[0]
        primary_amount = primary_posting.units.number
        currency = primary_posting.units.currency

        new_postings = list(txn.postings)

        for split in splits:
            # Calculate this split's portion of the opposite amount
            portion = split.percentage / Decimal("100")
            split_amount = -primary_amount * portion

            balancing_posting = data.Posting(
                split.account,
                Amount(split_amount, currency),
                None, None, None, None
            )
            new_postings.append(balancing_posting)

        return txn._replace(postings=new_postings)


# =============================================================================
# Beangulp Importer Mixin
# =============================================================================


class ClassifierMixin:
    """Mixin that provides transaction classification for beangulp importers.

    Add this mixin to your importer class to get automatic transaction
    categorization based on patterns.

    Your importer class must have a `transaction_patterns` attribute
    (list of TransactionPattern objects). Optionally, you can also set
    `default_account` and `default_split_percentage` attributes.

    Example:
        class MyImporter(ClassifierMixin, beangulp.Importer):
            def __init__(self, config):
                self.transaction_patterns = config.transaction_patterns
                self.default_account = config.default_account
                self.default_split_percentage = config.default_split_percentage
                # ... rest of your setup

            def extract(self, filepath, existing):
                # Your extraction logic
                # finalize() is provided by the mixin
                ...
    """

    # These attributes should be set by the importer class
    transaction_patterns: list[TransactionPattern]
    default_account: str | None = None
    default_split_percentage: Decimal | None = None

    def finalize(self, txn: data.Transaction, row: Any) -> data.Transaction | None:
        """Post-process the transaction with categorization based on patterns.

        This method is called by beangulp after extract() for each transaction.

        Args:
            txn: The transaction object to finalize
            row: The original source data (format-specific, passed through)

        Returns:
            The transaction with balancing posting(s) added based on classification,
            or the original transaction unchanged if no match and no default.
            Return None to skip/drop the transaction.
        """
        if not txn.postings:
            return txn

        # Get optional attributes with defaults
        default_account = getattr(self, 'default_account', None)
        default_split_percentage = getattr(self, 'default_split_percentage', None)
        patterns = getattr(self, 'transaction_patterns', [])

        # If no patterns and no default, return unchanged
        if not patterns and default_account is None:
            return txn

        classifier = TransactionClassifier(
            patterns,
            default_account=default_account,
            default_split_percentage=default_split_percentage,
        )
        narration = txn.narration or ""
        txn_amount = txn.postings[0].units.number

        if splits := classifier.classify(narration, txn_amount):
            return classifier.add_balancing_postings(txn, splits)

        return txn
