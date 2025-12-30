from datetime import date
from decimal import Decimal
from enum import Enum
from functools import cached_property
import re

from pydantic import BaseModel, Field, field_validator, model_validator


class RawTransaction(BaseModel):
    """Raw transaction data extracted from QBO file."""
    date: str | None = None
    amount: str | None = None
    payee: str | None = None
    memo: str | None = None
    id: str | None = None
    type: str | None = None


class ParsedTransaction(BaseModel):
    """Processed transaction with proper types."""
    date: date
    amount: Decimal
    payee: str | None = None
    memo: str | None = ""
    id: str | None = None
    type: str | None = None
    
    @field_validator('amount', mode='before')
    @classmethod
    def validate_amount(cls, v):
        """Ensure amount is a valid decimal."""
        return Decimal(v) if isinstance(v, str) else v


class BeanTransaction(BaseModel):
    """Transaction ready for conversion to Beancount entries."""
    model_config = {"arbitrary_types_allowed": True}

    date: date
    amount: Decimal
    currency: str
    payee: str | None = None
    narration: str = ""
    flag: str = "*"
    tags: set[str] = Field(default_factory=set)
    links: set[str] = Field(default_factory=set)
    account: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    matched_account: str | None = None


class QboFileData(BaseModel):
    """Data extracted from a QBO file."""
    transactions: list[RawTransaction] = Field(default_factory=list)
    balance: str | None = None
    balance_date: date | None = None
    currency: str | None = None
    account_id: str | None = None
    organization: str | None = None


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

        # Using helper functions for cleaner amount conditions
        TransactionPattern(amount_condition=amount_lt(50), account="Expenses:PettyCash")
        TransactionPattern(amount_condition=amount_between(100, 500), account="Expenses:Medium")

        # Combined: specific merchant with amount range
        TransactionPattern(
            narration="VINMONOPOLET",
            amount_condition=amount_gt(500),
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
# Helper functions for creating AmountCondition objects (fluent API)
# =============================================================================


def amount_lt(value: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'less than' comparison.

    Example:
        TransactionPattern(amount_condition=amount_lt(50), account="Expenses:Small")
    """
    return AmountCondition(operator=AmountOperator.LT, value=Decimal(str(value)))


def amount_lte(value: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'less than or equal' comparison."""
    return AmountCondition(operator=AmountOperator.LTE, value=Decimal(str(value)))


def amount_gt(value: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'greater than' comparison.

    Example:
        TransactionPattern(amount_condition=amount_gt(1000), account="Expenses:Large")
    """
    return AmountCondition(operator=AmountOperator.GT, value=Decimal(str(value)))


def amount_gte(value: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'greater than or equal' comparison."""
    return AmountCondition(operator=AmountOperator.GTE, value=Decimal(str(value)))


def amount_eq(value: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'equal' comparison.

    Example:
        TransactionPattern(amount_condition=amount_eq(99), account="Expenses:Subscriptions")
    """
    return AmountCondition(operator=AmountOperator.EQ, value=Decimal(str(value)))


def amount_between(low: AmountValue, high: AmountValue) -> AmountCondition:
    """Create an AmountCondition for 'between' comparison (inclusive).

    Example:
        TransactionPattern(amount_condition=amount_between(100, 500), account="Expenses:Medium")
    """
    return AmountCondition(
        operator=AmountOperator.BETWEEN,
        value=Decimal(str(low)),
        value2=Decimal(str(high)),
    )
