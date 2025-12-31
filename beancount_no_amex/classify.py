"""Transaction classification for humans.

A Pythonic, fluent API for categorizing financial transactions.
Works with any Beancount importer (OFX, CSV, MT940, etc.).

Quick Start:

    from beancount_no_amex import match, when, amount, TransactionClassifier

    rules = [
        # Simple substring matching
        match("SPOTIFY") >> "Expenses:Music",
        match("NETFLIX") >> "Expenses:Entertainment",

        # Regex patterns
        match(r"REMA\\s*1000").regex >> "Expenses:Groceries",

        # Case-insensitive matching
        match("starbucks").ignorecase >> "Expenses:Coffee",

        # Amount-based rules
        when(amount < 50) >> "Expenses:PettyCash",
        when(amount.between(100, 500)) >> "Expenses:Medium",

        # Combined conditions
        match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol:Fine",

        # Split across multiple accounts
        match("COSTCO") >> [
            ("Expenses:Groceries", 80),
            ("Expenses:Household", 20),
        ],

        # Shared expenses with roommates
        match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50),
    ]

    # Create classifier with optional default account
    classifier = TransactionClassifier(rules, default="Expenses:Uncategorized")

    # Classify a transaction
    result = classifier.classify("SPOTIFY Premium", Decimal("-9.99"))
    # => ClassificationResult with account="Expenses:Music"

Use with beangulp importers:

    from beancount_no_amex import match, amount, ClassifierMixin

    class MyImporter(ClassifierMixin, beangulp.Importer):
        def __init__(self):
            self.transaction_patterns = [
                match("SPOTIFY") >> "Expenses:Music",
                when(amount < 50) >> "Expenses:PettyCash",
            ]
            self.default_account = "Expenses:Uncategorized"
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from functools import cached_property
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union

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


class SharedExpense(BaseModel):
    """Track shared expenses with receivables and reimbursement offsets.

    When you pay for something that someone else owes you for (partially or fully),
    use this to generate the additional postings that track the receivable and
    offset your net expense.

    This creates a zero-sum pair of postings:
    - receivable_account: Positive amount (asset tracking what they owe you)
    - offset_account: Negative amount (income offsetting your expense)

    Example:
        SharedExpense(
            receivable_account="Assets:Receivables:Alex",
            offset_account="Income:Reimbursements",
            percentage=50,  # Alex owes 50%
        )

    For a -400 NOK grocery purchase with 50% shared, this generates:
        Liabilities:CreditCard      -400 NOK  (you paid)
        Expenses:Groceries           400 NOK  (full household expense)
        Assets:Receivables:Alex      200 NOK  (Alex owes you)
        Income:Reimbursements       -200 NOK  (offsets your net expense)

    Your net expense is 200 NOK, but Expenses:Groceries shows the true 400 NOK
    household spend for budgeting purposes.
    """
    receivable_account: str  # e.g., "Assets:Receivables:Alex"
    offset_account: str  # e.g., "Income:Reimbursements"
    percentage: Decimal  # Percentage of the expense they owe

    @field_validator('percentage', mode='before')
    @classmethod
    def validate_percentage(cls, v):
        """Ensure percentage is a valid decimal between 0 and 100."""
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
    """Pattern for matching transactions based on narration, amount, and/or fields.

    A pattern matches a transaction if ALL specified conditions are met:
    - If narration is specified, it must match (substring or regex)
    - If amount_condition is specified, the amount must satisfy it
    - If fields is specified, all field patterns must match

    At least one of narration, amount_condition, or fields must be specified.
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

        # Field-based matching (for CSV imports, bank account numbers, etc.)
        TransactionPattern(
            fields={"to_account": "98712345678"},
            account="Assets:Bank:Savings",
        )

        # Field matching with regex
        TransactionPattern(
            fields={"merchant_code": r"5411|5412"},  # Grocery MCCs
            fields_regex=True,
            account="Expenses:Groceries",
        )

        # Combined field + narration matching
        TransactionPattern(
            fields={"transaction_type": "ATM"},
            amount_condition=amount > 500,
            account="Expenses:Cash:Large",
        )

        # Split transaction across multiple accounts
        TransactionPattern(
            narration="COSTCO",
            splits=[
                AccountSplit(account="Expenses:Groceries", percentage=80),
                AccountSplit(account="Expenses:Household", percentage=20),
            ]
        )

        # Shared expense with receivables tracking
        TransactionPattern(
            narration="REMA 1000",
            account="Expenses:Groceries",
            shared_with=[
                SharedExpense(
                    receivable_account="Assets:Receivables:Alex",
                    offset_account="Income:Reimbursements",
                    percentage=50,  # Alex owes 50%
                ),
            ]
        )
    """
    narration: str | None = None
    regex: bool = False  # If True, narration is treated as a regex pattern
    case_insensitive: bool = False  # If True, narration matching is case-insensitive
    amount_condition: AmountCondition | None = None
    fields: dict[str, str] | None = None  # Field name -> pattern for matching
    fields_regex: bool = False  # If True, field patterns are treated as regex
    account: str | None = None  # Target account (single), mutually exclusive with splits
    splits: list[AccountSplit] | None = None  # Split across multiple accounts
    shared_with: list[SharedExpense] | None = None  # Track shared expenses with others

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode='after')
    def validate_pattern(self):
        """Validate pattern configuration."""
        # Must have at least one matching condition
        if self.narration is None and self.amount_condition is None and self.fields is None:
            raise ValueError("At least one of narration, amount_condition, or fields must be specified")

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

        # Validate shared_with percentages sum to <= 100
        if self.shared_with is not None:
            total = sum(s.percentage for s in self.shared_with)
            if total > 100:
                raise ValueError(f"shared_with percentages sum to {total}, must be <= 100")

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

    @cached_property
    def _compiled_field_patterns(self) -> dict[str, re.Pattern] | None:
        """Lazily compile and cache regex patterns for field matching."""
        if self.fields is None:
            return None

        compiled = {}
        for field_name, pattern in self.fields.items():
            if self.fields_regex:
                compiled[field_name] = re.compile(pattern)
            else:
                # For non-regex, escape special characters for literal matching
                compiled[field_name] = re.compile(re.escape(pattern))
        return compiled

    def matches(
        self,
        narration: str,
        amount: Decimal,
        fields: dict[str, str] | None = None,
    ) -> bool:
        """Check if a transaction matches this pattern.

        Args:
            narration: The transaction narration/description
            amount: The transaction amount
            fields: Optional dictionary of field names to values for matching

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

        # Check field conditions
        if self.fields is not None:
            if fields is None:
                return False
            if self._compiled_field_patterns is None:
                return False
            for field_name, pattern in self._compiled_field_patterns.items():
                field_value = fields.get(field_name, "")
                if pattern.search(field_value) is None:
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
# Fluent API - "Classification for Humans"
# =============================================================================

# Type for split specifications: list of (account, percentage) tuples
SplitSpec = list[tuple[str, int | float | Decimal]]


class _SharedExpenseSpec:
    """Specification for shared expense, used with | operator."""

    def __init__(
        self,
        receivable_account: str,
        percentage: int | float | Decimal,
        offset_account: str = "Income:Reimbursements",
    ):
        self.receivable_account = receivable_account
        self.offset_account = offset_account
        self.percentage = Decimal(str(percentage))


def shared(
    receivable: str,
    percentage: int | float | Decimal,
    offset: str = "Income:Reimbursements",
) -> _SharedExpenseSpec:
    """Create a shared expense specification.

    Use with the | operator after >> to track shared expenses:

        match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50)

    Args:
        receivable: Account to track what they owe (e.g., "Assets:Receivables:Alex")
        percentage: Percentage of expense they owe (0-100)
        offset: Income account for reimbursement offset (default: "Income:Reimbursements")

    Returns:
        A SharedExpenseSpec for use with the | operator
    """
    return _SharedExpenseSpec(receivable, percentage, offset)


class _PatternResult:
    """Result of >> operator, can be combined with | for shared expenses."""

    def __init__(self, pattern: TransactionPattern):
        self.pattern = pattern

    def __or__(self, other: _SharedExpenseSpec) -> "_PatternResult":
        """Add shared expense tracking with | operator."""
        if not isinstance(other, _SharedExpenseSpec):
            raise TypeError(f"Cannot use | with {type(other).__name__}, use shared()")

        # Add to existing shared_with list or create new one
        existing = list(self.pattern.shared_with or [])
        existing.append(SharedExpense(
            receivable_account=other.receivable_account,
            offset_account=other.offset_account,
            percentage=other.percentage,
        ))

        # Create new pattern with updated shared_with
        self.pattern = TransactionPattern(
            narration=self.pattern.narration,
            regex=self.pattern.regex,
            case_insensitive=self.pattern.case_insensitive,
            amount_condition=self.pattern.amount_condition,
            fields=self.pattern.fields,
            fields_regex=self.pattern.fields_regex,
            account=self.pattern.account,
            splits=self.pattern.splits,
            shared_with=existing,
        )
        return self

    def build(self) -> TransactionPattern:
        """Get the underlying TransactionPattern."""
        return self.pattern


class _MatchBuilder:
    """Fluent builder for creating transaction patterns.

    Created by match() or field(), supports chaining and >> operator.

    Examples:
        match("SPOTIFY") >> "Expenses:Music"
        match(r"REMA\\s*1000").regex >> "Expenses:Groceries"
        match("spotify").ignorecase >> "Expenses:Music"
        match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol"
    """

    def __init__(
        self,
        narration: str | None = None,
        *,
        is_regex: bool = False,
        ignore_case: bool = False,
        amount_cond: AmountCondition | None = None,
        fields: dict[str, str] | None = None,
        fields_regex: bool = False,
    ):
        self._narration = narration
        self._is_regex = is_regex
        self._ignore_case = ignore_case
        self._amount_cond = amount_cond
        self._fields = fields
        self._fields_regex = fields_regex

    @property
    def regex(self) -> "_MatchBuilder":
        """Treat the pattern as a regular expression.

        Example:
            match(r"REMA\\s*1000").regex >> "Expenses:Groceries"
        """
        return _MatchBuilder(
            self._narration,
            is_regex=True,
            ignore_case=self._ignore_case,
            amount_cond=self._amount_cond,
            fields=self._fields,
            fields_regex=self._fields_regex,
        )

    @property
    def ignorecase(self) -> "_MatchBuilder":
        """Make the match case-insensitive.

        Example:
            match("spotify").ignorecase >> "Expenses:Music"
        """
        return _MatchBuilder(
            self._narration,
            is_regex=self._is_regex,
            ignore_case=True,
            amount_cond=self._amount_cond,
            fields=self._fields,
            fields_regex=self._fields_regex,
        )

    # Alias for ignorecase
    @property
    def i(self) -> "_MatchBuilder":
        """Short alias for ignorecase.

        Example:
            match("spotify").i >> "Expenses:Music"
        """
        return self.ignorecase

    def where(self, condition: AmountCondition | "_FieldBuilder") -> "_MatchBuilder":
        """Add an additional condition (amount or field).

        Examples:
            match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol"
            match("ATM").where(field(type="withdrawal")) >> "Expenses:Cash"
        """
        if isinstance(condition, AmountCondition):
            return _MatchBuilder(
                self._narration,
                is_regex=self._is_regex,
                ignore_case=self._ignore_case,
                amount_cond=condition,
                fields=self._fields,
                fields_regex=self._fields_regex,
            )
        elif isinstance(condition, _FieldBuilder):
            # Merge fields
            merged = dict(self._fields or {})
            merged.update(condition._fields or {})
            return _MatchBuilder(
                self._narration,
                is_regex=self._is_regex,
                ignore_case=self._ignore_case,
                amount_cond=self._amount_cond,
                fields=merged,
                fields_regex=condition._fields_regex or self._fields_regex,
            )
        else:
            raise TypeError(f"where() expects AmountCondition or field(), got {type(condition)}")

    def _build_pattern(
        self,
        account: str | None = None,
        splits: list[AccountSplit] | None = None,
    ) -> TransactionPattern:
        """Build the TransactionPattern from current state."""
        return TransactionPattern(
            narration=self._narration,
            regex=self._is_regex,
            case_insensitive=self._ignore_case,
            amount_condition=self._amount_cond,
            fields=self._fields,
            fields_regex=self._fields_regex,
            account=account,
            splits=splits,
        )

    def __rshift__(self, target: str | SplitSpec) -> _PatternResult:
        """Create pattern with >> operator.

        Examples:
            match("SPOTIFY") >> "Expenses:Music"
            match("COSTCO") >> [("Expenses:Groceries", 80), ("Expenses:Household", 20)]
        """
        if isinstance(target, str):
            return _PatternResult(self._build_pattern(account=target))
        elif isinstance(target, list):
            splits = [
                AccountSplit(account=acct, percentage=Decimal(str(pct)))
                for acct, pct in target
            ]
            return _PatternResult(self._build_pattern(splits=splits))
        else:
            raise TypeError(f">> expects str or list of (account, pct) tuples, got {type(target)}")


class _FieldBuilder(_MatchBuilder):
    """Builder for field-based patterns.

    Created by field(), can be used standalone or with .where().

    Examples:
        field(to_account="98712345678") >> "Assets:Savings"
        field(merchant_code=r"5411|5412").regex >> "Expenses:Groceries"
    """

    def __init__(
        self,
        fields: dict[str, str],
        fields_regex: bool = False,
    ):
        super().__init__(
            narration=None,
            fields=fields,
            fields_regex=fields_regex,
        )

    @property
    def regex(self) -> "_FieldBuilder":
        """Treat field patterns as regular expressions."""
        return _FieldBuilder(self._fields, fields_regex=True)


class _WhenBuilder:
    """Builder for condition-only patterns (no narration).

    Created by when(), for amount-based classification.

    Examples:
        when(amount < 50) >> "Expenses:PettyCash"
        when(amount.between(100, 500)) >> "Expenses:Medium"
    """

    def __init__(self, condition: AmountCondition):
        self._condition = condition

    def __rshift__(self, target: str | SplitSpec) -> _PatternResult:
        """Create pattern with >> operator."""
        if isinstance(target, str):
            pattern = TransactionPattern(
                amount_condition=self._condition,
                account=target,
            )
            return _PatternResult(pattern)
        elif isinstance(target, list):
            splits = [
                AccountSplit(account=acct, percentage=Decimal(str(pct)))
                for acct, pct in target
            ]
            pattern = TransactionPattern(
                amount_condition=self._condition,
                splits=splits,
            )
            return _PatternResult(pattern)
        else:
            raise TypeError(f">> expects str or list of (account, pct) tuples, got {type(target)}")


def match(pattern: str) -> _MatchBuilder:
    """Start building a narration-based pattern.

    This is the primary entry point for the fluent API. Patterns match
    as substrings by default. Use .regex for regular expression matching.

    Examples:
        # Simple substring match
        match("SPOTIFY") >> "Expenses:Music"

        # Regex pattern
        match(r"REMA\\s*1000").regex >> "Expenses:Groceries"

        # Case-insensitive
        match("spotify").ignorecase >> "Expenses:Music"
        match("spotify").i >> "Expenses:Music"  # short form

        # With amount condition
        match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol:Expensive"

        # Split across accounts
        match("COSTCO") >> [
            ("Expenses:Groceries", 80),
            ("Expenses:Household", 20),
        ]

        # With shared expense tracking
        match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50)

    Args:
        pattern: The narration pattern to match (substring or regex)

    Returns:
        A builder that can be chained and finalized with >>
    """
    return _MatchBuilder(pattern)


def when(condition: AmountCondition) -> _WhenBuilder:
    """Start building an amount-based pattern.

    Use this for patterns that match based on transaction amount only,
    without matching the narration text.

    Examples:
        when(amount < 50) >> "Expenses:PettyCash"
        when(amount > 1000) >> "Expenses:Large"
        when(amount.between(100, 500)) >> "Expenses:Medium"

    Args:
        condition: An amount condition (use the `amount` proxy)

    Returns:
        A builder that can be finalized with >>
    """
    if not isinstance(condition, AmountCondition):
        raise TypeError("when() expects an amount condition like: amount < 50")
    return _WhenBuilder(condition)


def field(**kwargs: str) -> _FieldBuilder:
    """Start building a field-based pattern.

    Use this for patterns that match on metadata fields (bank account
    numbers, transaction types, merchant codes, etc.).

    Examples:
        # Match specific account number
        field(to_account="98712345678") >> "Assets:Savings"

        # Regex pattern for merchant category codes
        field(merchant_code=r"5411|5412").regex >> "Expenses:Groceries"

        # Multiple fields (all must match)
        field(type="ATM", location="Oslo") >> "Expenses:Cash"

        # Combine with narration matching
        match("TRANSFER").where(field(to_account="12345")) >> "Assets:Savings"

    Args:
        **kwargs: Field name to pattern mappings

    Returns:
        A builder that can be chained and finalized with >>
    """
    if not kwargs:
        raise ValueError("field() requires at least one field=pattern argument")
    return _FieldBuilder(kwargs)


# =============================================================================
# Classification Result
# =============================================================================


class ClassificationResult(BaseModel):
    """Result of classifying a transaction.

    Contains both the expense splits and any shared expense tracking info.
    """
    splits: list[AccountSplit]
    shared_with: list[SharedExpense] | None = None


# =============================================================================
# Transaction Classifier
# =============================================================================


# Type alias for pattern inputs (both old and fluent API)
PatternInput = TransactionPattern | _PatternResult


def _normalize_patterns(
    patterns: list[PatternInput],
) -> list[TransactionPattern]:
    """Convert fluent API patterns to TransactionPattern objects.

    Accepts both TransactionPattern objects and _PatternResult objects
    (from the fluent API's >> operator).
    """
    result = []
    for p in patterns:
        if isinstance(p, _PatternResult):
            result.append(p.pattern)
        elif isinstance(p, TransactionPattern):
            result.append(p)
        else:
            raise TypeError(
                f"Expected TransactionPattern or fluent pattern (match() >> ...), "
                f"got {type(p).__name__}"
            )
    return result


class TransactionClassifier:
    """Generic transaction classifier that matches patterns against transactions.

    This class can be used standalone or through the ClassifierMixin.

    Example using fluent API:
        from beancount_no_amex import match, when, amount, TransactionClassifier

        rules = [
            match("SPOTIFY") >> "Expenses:Music",
            match(r"REMA\\s*1000").regex >> "Expenses:Groceries",
            when(amount < 50) >> "Expenses:PettyCash",
        ]

        classifier = TransactionClassifier(rules, default="Expenses:Uncategorized")
        result = classifier.classify("SPOTIFY Premium", Decimal("-9.99"))

    Example with traditional API:
        classifier = TransactionClassifier(patterns)
        splits = classifier.classify("SPOTIFY PREMIUM", Decimal("-9.99"))
        if splits:
            for split in splits.splits:
                print(f"  {split.percentage}% -> {split.account}")

        # With default account for unmatched transactions
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:Uncategorized"
        )

        # With default split percentage (for review workflow)
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("50")  # 50% confident
        )
    """

    def __init__(
        self,
        patterns: list[PatternInput],
        default_account: str | None = None,
        default_split_percentage: Decimal | None = None,
        *,
        default: str | None = None,  # Alias for default_account (shorter)
    ):
        """Initialize the classifier with patterns and optional defaults.

        Args:
            patterns: List of patterns. Accepts TransactionPattern objects or
                     fluent API patterns (match() >> "Account"). Patterns are
                     evaluated in order; the first match wins.
            default_account: Account for unmatched transactions. When set,
                           unmatched transactions go 100% to this account.
            default: Alias for default_account (use whichever you prefer).
            default_split_percentage: When set (0-100), matched transactions are
                           split: (100 - this value)% to matched account(s),
                           this value % to default_account. Requires default_account.
                           Set to None to disable (default).
        """
        self.patterns = _normalize_patterns(patterns)
        self.default_account = default_account or default
        self.default_split_percentage = default_split_percentage

        # Validate: default_split_percentage requires default_account
        if default_split_percentage is not None and self.default_account is None:
            raise ValueError("default_split_percentage requires default_account to be set")

    def classify(
        self,
        narration: str,
        amount: Decimal,
        fields: dict[str, str] | None = None,
    ) -> ClassificationResult | None:
        """Find the matching account(s) for a transaction.

        Args:
            narration: The transaction narration/description
            amount: The transaction amount
            fields: Optional dictionary of field names to values for matching

        Returns:
            A ClassificationResult with splits and shared_with info,
            or None if no match and no default_account is configured.

            When default_split_percentage is set, matched transactions are split
            between the matched account(s) and default_account.
        """
        # Find matching pattern
        matched_pattern = None
        for pattern in self.patterns:
            if pattern.matches(narration, amount, fields):
                matched_pattern = pattern
                break

        if matched_pattern is not None:
            # Get the pattern's splits
            splits = matched_pattern.get_splits()
            shared_with = matched_pattern.shared_with

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
                return ClassificationResult(splits=scaled_splits, shared_with=shared_with)

            return ClassificationResult(splits=splits, shared_with=shared_with)

        # No match - use default_account if configured
        if self.default_account is not None:
            return ClassificationResult(
                splits=[AccountSplit(account=self.default_account, percentage=Decimal("100"))]
            )

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
        result = ClassificationResult(
            splits=[AccountSplit(account=account, percentage=Decimal("100"))]
        )
        return self.add_balancing_postings(txn, result)

    def add_balancing_postings(
        self,
        txn: data.Transaction,
        result: ClassificationResult,
    ) -> data.Transaction:
        """Add balancing postings to a transaction based on classification result.

        Creates postings with opposite amounts proportional to each split's
        percentage to balance the transaction. Also adds shared expense
        postings if configured (receivable + offset pairs).

        Args:
            txn: The transaction to modify (must have at least one posting)
            result: ClassificationResult with splits and optional shared_with

        Returns:
            A new transaction with the balancing postings added
        """
        if not txn.postings or not result.splits:
            return txn

        primary_posting = txn.postings[0]
        primary_amount = primary_posting.units.number
        currency = primary_posting.units.currency

        new_postings = list(txn.postings)

        # Add expense splits (balancing postings)
        for split in result.splits:
            # Calculate this split's portion of the opposite amount
            portion = split.percentage / Decimal("100")
            split_amount = -primary_amount * portion

            balancing_posting = data.Posting(
                split.account,
                Amount(split_amount, currency),
                None, None, None, None
            )
            new_postings.append(balancing_posting)

        # Add shared expense postings (receivable + offset pairs)
        if result.shared_with:
            for shared in result.shared_with:
                portion = shared.percentage / Decimal("100")
                # The receivable amount is positive (they owe you)
                # For a debit (negative primary), receivable should be positive
                receivable_amount = -primary_amount * portion

                # Receivable posting (positive: asset tracking what they owe)
                receivable_posting = data.Posting(
                    shared.receivable_account,
                    Amount(receivable_amount, currency),
                    None, None, None, None
                )
                new_postings.append(receivable_posting)

                # Offset posting (negative: income offsetting your expense)
                offset_posting = data.Posting(
                    shared.offset_account,
                    Amount(-receivable_amount, currency),
                    None, None, None, None
                )
                new_postings.append(offset_posting)

        return txn._replace(postings=new_postings)


# =============================================================================
# Beangulp Importer Mixin
# =============================================================================


class ClassifierMixin:
    """Mixin that provides transaction classification for beangulp importers.

    Add this mixin to your importer class to get automatic transaction
    categorization based on patterns.

    Your importer class must have a `transaction_patterns` attribute
    (list of patterns). Optionally, you can also set `default_account`
    and `default_split_percentage` attributes.

    For field-based matching, override the `get_fields()` method to extract
    fields from your source data format.

    Example with fluent API:
        from beancount_no_amex import match, when, amount, ClassifierMixin

        class MyImporter(ClassifierMixin, beangulp.Importer):
            def __init__(self, config):
                self.transaction_patterns = [
                    match("SPOTIFY") >> "Expenses:Music",
                    match(r"REMA\\s*1000").regex >> "Expenses:Groceries",
                    when(amount < 50) >> "Expenses:PettyCash",
                ]
                self.default_account = "Expenses:Uncategorized"

    Example with traditional API:
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

            # Optional: override to enable field-based matching
            def get_fields(self, row) -> dict[str, str] | None:
                return {
                    "to_account": row.to_account,
                    "transaction_type": row.type,
                }
    """

    # These attributes should be set by the importer class
    transaction_patterns: list[PatternInput]
    default_account: str | None = None
    default_split_percentage: Decimal | None = None

    def get_fields(self, row: Any) -> dict[str, str] | None:
        """Extract fields from the source row for pattern matching.

        Override this method in your importer to enable field-based matching.
        The returned dictionary maps field names to string values.

        Args:
            row: The original source data (format-specific)

        Returns:
            A dictionary of field names to values, or None if no fields available.
        """
        return None

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
        fields = self.get_fields(row)

        if result := classifier.classify(narration, txn_amount, fields):
            return classifier.add_balancing_postings(txn, result)

        return txn
