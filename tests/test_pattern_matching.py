"""Tests for TransactionPattern and AmountCondition models.

These tests verify the pattern matching logic for:
- Narration substring matching
- Regex matching (with case sensitivity options)
- Amount-based conditions (lt, lte, gt, gte, eq, between)
- Combined narration + amount matching
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from beancount_classifier import (
    AccountSplit,
    AmountCondition,
    AmountOperator,
    ClassificationResult,
    SharedExpense,
    TransactionClassifier,
    TransactionPattern,
    amount,
)


class TestAmountCondition:
    """Tests for AmountCondition matching logic."""

    def test_less_than_matches(self):
        """LT operator matches amounts strictly less than value."""
        condition = AmountCondition(operator=AmountOperator.LT, value=Decimal("100"))
        assert condition.matches(Decimal("99.99")) is True
        assert condition.matches(Decimal("50")) is True
        assert condition.matches(Decimal("100")) is False
        assert condition.matches(Decimal("100.01")) is False

    def test_less_than_or_equal_matches(self):
        """LTE operator matches amounts less than or equal to value."""
        condition = AmountCondition(operator=AmountOperator.LTE, value=Decimal("100"))
        assert condition.matches(Decimal("99.99")) is True
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("100.01")) is False

    def test_greater_than_matches(self):
        """GT operator matches amounts strictly greater than value."""
        condition = AmountCondition(operator=AmountOperator.GT, value=Decimal("100"))
        assert condition.matches(Decimal("100.01")) is True
        assert condition.matches(Decimal("500")) is True
        assert condition.matches(Decimal("100")) is False
        assert condition.matches(Decimal("99.99")) is False

    def test_greater_than_or_equal_matches(self):
        """GTE operator matches amounts greater than or equal to value."""
        condition = AmountCondition(operator=AmountOperator.GTE, value=Decimal("100"))
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("100.01")) is True
        assert condition.matches(Decimal("99.99")) is False

    def test_equal_matches(self):
        """EQ operator matches amounts exactly equal to value."""
        condition = AmountCondition(operator=AmountOperator.EQ, value=Decimal("100"))
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("100.00")) is True
        assert condition.matches(Decimal("99.99")) is False
        assert condition.matches(Decimal("100.01")) is False

    def test_between_matches(self):
        """BETWEEN operator matches amounts within range (inclusive)."""
        condition = AmountCondition(
            operator=AmountOperator.BETWEEN,
            value=Decimal("50"),
            value2=Decimal("100"),
        )
        assert condition.matches(Decimal("50")) is True  # Lower bound
        assert condition.matches(Decimal("75")) is True  # Middle
        assert condition.matches(Decimal("100")) is True  # Upper bound
        assert condition.matches(Decimal("49.99")) is False  # Below range
        assert condition.matches(Decimal("100.01")) is False  # Above range

    def test_between_requires_value2(self):
        """BETWEEN operator requires value2 to be specified."""
        with pytest.raises(ValidationError):
            AmountCondition(operator=AmountOperator.BETWEEN, value=Decimal("50"))

    def test_uses_absolute_value(self):
        """Amount matching uses absolute value (works for debits and credits)."""
        condition = AmountCondition(operator=AmountOperator.LT, value=Decimal("100"))
        # Negative (debit) amount
        assert condition.matches(Decimal("-50")) is True
        assert condition.matches(Decimal("-99.99")) is True
        assert condition.matches(Decimal("-100")) is False

    def test_value_coercion_from_string(self):
        """Values can be specified as strings."""
        condition = AmountCondition(operator=AmountOperator.EQ, value="100.50")
        assert condition.value == Decimal("100.50")

    def test_value_coercion_from_int(self):
        """Values can be specified as integers."""
        condition = AmountCondition(operator=AmountOperator.EQ, value=100)
        assert condition.value == Decimal("100")


class TestTransactionPatternNarration:
    """Tests for narration-based pattern matching."""

    def test_substring_match(self):
        """Simple substring matching (default behavior)."""
        pattern = TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        assert pattern.matches("Premium SPOTIFY Subscription", Decimal("100")) is True
        assert pattern.matches("SPOTIFY", Decimal("100")) is True
        assert pattern.matches("spotify", Decimal("100")) is False  # Case sensitive

    def test_case_insensitive_substring_match(self):
        """Case-insensitive substring matching."""
        pattern = TransactionPattern(
            narration="spotify",
            case_insensitive=True,
            account="Expenses:Music",
        )
        assert pattern.matches("SPOTIFY", Decimal("100")) is True
        assert pattern.matches("Spotify Premium", Decimal("100")) is True
        assert pattern.matches("spotify", Decimal("100")) is True

    def test_regex_match(self):
        """Regex pattern matching."""
        pattern = TransactionPattern(
            narration=r"REMA\s*1000",
            regex=True,
            account="Expenses:Groceries",
        )
        assert pattern.matches("REMA 1000 OSLO", Decimal("100")) is True
        assert pattern.matches("REMA1000", Decimal("100")) is True
        assert pattern.matches("REMA  1000", Decimal("100")) is True
        assert pattern.matches("REMA 2000", Decimal("100")) is False

    def test_regex_case_insensitive(self):
        """Case-insensitive regex matching."""
        pattern = TransactionPattern(
            narration=r"rema\s*1000",
            regex=True,
            case_insensitive=True,
            account="Expenses:Groceries",
        )
        assert pattern.matches("REMA 1000", Decimal("100")) is True
        assert pattern.matches("rema1000", Decimal("100")) is True

    def test_special_regex_chars_escaped_in_substring(self):
        """Special regex characters are escaped in substring mode."""
        pattern = TransactionPattern(
            narration="STORE (NYC)",
            account="Expenses:Shopping",
        )
        assert pattern.matches("STORE (NYC) Purchase", Decimal("100")) is True
        # Without escaping, parentheses would be treated as a group

    def test_narration_pattern_caching(self):
        """Compiled regex pattern is cached."""
        pattern = TransactionPattern(narration="TEST", account="Expenses:Test")
        # First match compiles the pattern
        pattern.matches("TEST", Decimal("100"))
        # Pattern should be cached now
        assert pattern._compiled_pattern is not None


class TestTransactionPatternAmount:
    """Tests for amount-only pattern matching."""

    def test_amount_only_pattern(self):
        """Pattern with only amount condition (no narration)."""
        pattern = TransactionPattern(
            amount_condition=AmountCondition(
                operator=AmountOperator.LT, value=Decimal("50")
            ),
            account="Expenses:PettyCash",
        )
        assert pattern.matches("ANY MERCHANT", Decimal("25")) is True
        assert pattern.matches("DIFFERENT MERCHANT", Decimal("49.99")) is True
        assert pattern.matches("ANOTHER ONE", Decimal("50")) is False

    def test_amount_range_pattern(self):
        """Pattern matching a specific amount range."""
        pattern = TransactionPattern(
            amount_condition=AmountCondition(
                operator=AmountOperator.BETWEEN,
                value=Decimal("100"),
                value2=Decimal("500"),
            ),
            account="Expenses:MediumPurchases",
        )
        assert pattern.matches("ANY", Decimal("100")) is True
        assert pattern.matches("ANY", Decimal("250")) is True
        assert pattern.matches("ANY", Decimal("500")) is True
        assert pattern.matches("ANY", Decimal("99")) is False
        assert pattern.matches("ANY", Decimal("501")) is False


class TestTransactionPatternCombined:
    """Tests for combined narration + amount pattern matching."""

    def test_both_conditions_must_match(self):
        """Both narration AND amount must match."""
        pattern = TransactionPattern(
            narration="VINMONOPOLET",
            amount_condition=AmountCondition(
                operator=AmountOperator.GT, value=Decimal("500")
            ),
            account="Expenses:Alcohol:Expensive",
        )
        # Both match
        assert pattern.matches("VINMONOPOLET OSLO", Decimal("750")) is True
        # Only narration matches
        assert pattern.matches("VINMONOPOLET OSLO", Decimal("100")) is False
        # Only amount matches
        assert pattern.matches("OTHER STORE", Decimal("750")) is False
        # Neither matches
        assert pattern.matches("OTHER STORE", Decimal("100")) is False

    def test_combined_with_regex(self):
        """Combined pattern with regex narration matching."""
        pattern = TransactionPattern(
            narration=r"(UBER|LYFT)",
            regex=True,
            amount_condition=AmountCondition(
                operator=AmountOperator.LTE, value=Decimal("100")
            ),
            account="Expenses:Transportation:Rideshare",
        )
        assert pattern.matches("UBER TRIP", Decimal("50")) is True
        assert pattern.matches("LYFT RIDE", Decimal("100")) is True
        assert pattern.matches("UBER TRIP", Decimal("150")) is False  # Too expensive


class TestTransactionPatternValidation:
    """Tests for TransactionPattern validation."""

    def test_requires_at_least_one_condition(self):
        """At least one of narration, amount_condition, or fields must be specified."""
        with pytest.raises(ValidationError):
            TransactionPattern(account="Expenses:Test")

    def test_account_is_required(self):
        """Account field is required."""
        with pytest.raises(ValidationError):
            TransactionPattern(narration="TEST")

    def test_valid_pattern_with_narration_only(self):
        """Pattern with only narration is valid."""
        pattern = TransactionPattern(narration="TEST", account="Expenses:Test")
        assert pattern.narration == "TEST"

    def test_valid_pattern_with_amount_only(self):
        """Pattern with only amount condition is valid."""
        pattern = TransactionPattern(
            amount_condition=AmountCondition(
                operator=AmountOperator.LT, value=Decimal("100")
            ),
            account="Expenses:Test",
        )
        assert pattern.amount_condition is not None


class TestAmountProxy:
    """Tests for the amount proxy with natural comparison syntax."""

    def test_less_than(self):
        """amount < value creates correct AmountCondition."""
        condition = amount < 100
        assert condition.operator == AmountOperator.LT
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("99")) is True
        assert condition.matches(Decimal("100")) is False

    def test_less_than_or_equal(self):
        """amount <= value creates correct AmountCondition."""
        condition = amount <= 100
        assert condition.operator == AmountOperator.LTE
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("101")) is False

    def test_greater_than(self):
        """amount > value creates correct AmountCondition."""
        condition = amount > 100
        assert condition.operator == AmountOperator.GT
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("101")) is True
        assert condition.matches(Decimal("100")) is False

    def test_greater_than_or_equal(self):
        """amount >= value creates correct AmountCondition."""
        condition = amount >= 100
        assert condition.operator == AmountOperator.GTE
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("99")) is False

    def test_equal(self):
        """amount == value creates correct AmountCondition."""
        condition = amount == 99.99
        assert condition.operator == AmountOperator.EQ
        assert condition.value == Decimal("99.99")
        assert condition.matches(Decimal("99.99")) is True
        assert condition.matches(Decimal("100")) is False

    def test_between(self):
        """amount.between(low, high) creates correct AmountCondition."""
        condition = amount.between(50, 100)
        assert condition.operator == AmountOperator.BETWEEN
        assert condition.value == Decimal("50")
        assert condition.value2 == Decimal("100")
        assert condition.matches(Decimal("75")) is True
        assert condition.matches(Decimal("49")) is False

    def test_accepts_various_types(self):
        """Amount proxy accepts int, float, string, and Decimal."""
        # Integer
        assert (amount < 100).value == Decimal("100")
        # Float
        assert (amount < 99.99).value == Decimal("99.99")
        # String
        assert (amount < "50.50").value == Decimal("50.50")
        # Decimal
        assert (amount < Decimal("25")).value == Decimal("25")

    def test_in_transaction_pattern(self):
        """Amount proxy works seamlessly with TransactionPattern."""
        pattern = TransactionPattern(
            narration="TEST",
            amount_condition=amount > 500,
            account="Expenses:Large",
        )
        assert pattern.matches("TEST MERCHANT", Decimal("600")) is True
        assert pattern.matches("TEST MERCHANT", Decimal("400")) is False

    def test_all_operators_in_patterns(self):
        """All comparison operators work in TransactionPattern."""
        patterns = [
            TransactionPattern(amount_condition=amount < 50, account="A"),
            TransactionPattern(amount_condition=amount <= 50, account="B"),
            TransactionPattern(amount_condition=amount > 50, account="C"),
            TransactionPattern(amount_condition=amount >= 50, account="D"),
            TransactionPattern(amount_condition=amount == 50, account="E"),
            TransactionPattern(amount_condition=amount.between(40, 60), account="F"),
        ]
        # Just verify they all construct without error
        assert len(patterns) == 6


class TestAccountSplit:
    """Tests for AccountSplit model."""

    def test_create_split(self):
        """Basic AccountSplit creation."""
        split = AccountSplit(account="Expenses:Groceries", percentage=Decimal("80"))
        assert split.account == "Expenses:Groceries"
        assert split.percentage == Decimal("80")

    def test_percentage_coercion_from_int(self):
        """Percentage can be specified as int."""
        split = AccountSplit(account="Expenses:Test", percentage=50)
        assert split.percentage == Decimal("50")

    def test_percentage_coercion_from_float(self):
        """Percentage can be specified as float."""
        split = AccountSplit(account="Expenses:Test", percentage=33.33)
        assert split.percentage == Decimal("33.33")

    def test_percentage_coercion_from_string(self):
        """Percentage can be specified as string."""
        split = AccountSplit(account="Expenses:Test", percentage="25.5")
        assert split.percentage == Decimal("25.5")

    def test_percentage_must_be_between_0_and_100(self):
        """Percentage must be in valid range."""
        with pytest.raises(ValidationError):
            AccountSplit(account="Expenses:Test", percentage=-10)
        with pytest.raises(ValidationError):
            AccountSplit(account="Expenses:Test", percentage=101)

    def test_percentage_boundary_values(self):
        """Percentage can be exactly 0 or 100."""
        split_zero = AccountSplit(account="A", percentage=0)
        assert split_zero.percentage == Decimal("0")
        split_hundred = AccountSplit(account="B", percentage=100)
        assert split_hundred.percentage == Decimal("100")


class TestTransactionPatternSplits:
    """Tests for TransactionPattern with splits."""

    def test_pattern_with_splits(self):
        """Pattern can specify multiple account splits."""
        pattern = TransactionPattern(
            narration="COSTCO",
            splits=[
                AccountSplit(account="Expenses:Groceries", percentage=80),
                AccountSplit(account="Expenses:Household", percentage=20),
            ]
        )
        assert len(pattern.splits) == 2
        assert pattern.splits[0].account == "Expenses:Groceries"
        assert pattern.splits[0].percentage == Decimal("80")

    def test_pattern_must_have_account_or_splits(self):
        """Pattern must specify either account or splits."""
        with pytest.raises(ValidationError):
            TransactionPattern(narration="TEST")

    def test_pattern_cannot_have_both_account_and_splits(self):
        """Pattern cannot specify both account and splits."""
        with pytest.raises(ValidationError):
            TransactionPattern(
                narration="TEST",
                account="Expenses:Test",
                splits=[AccountSplit(account="Expenses:Other", percentage=100)],
            )

    def test_splits_percentage_cannot_exceed_100(self):
        """Split percentages cannot sum to more than 100."""
        with pytest.raises(ValidationError):
            TransactionPattern(
                narration="TEST",
                splits=[
                    AccountSplit(account="A", percentage=60),
                    AccountSplit(account="B", percentage=50),
                ],
            )

    def test_splits_percentage_can_be_less_than_100(self):
        """Split percentages can sum to less than 100 (remainder unallocated)."""
        pattern = TransactionPattern(
            narration="TEST",
            splits=[
                AccountSplit(account="A", percentage=40),
                AccountSplit(account="B", percentage=30),
            ],
        )
        total = sum(s.percentage for s in pattern.splits)
        assert total == Decimal("70")

    def test_get_splits_for_single_account(self):
        """get_splits() returns 100% split for single account pattern."""
        pattern = TransactionPattern(narration="TEST", account="Expenses:Test")
        splits = pattern.get_splits()
        assert len(splits) == 1
        assert splits[0].account == "Expenses:Test"
        assert splits[0].percentage == Decimal("100")

    def test_get_splits_for_multi_account(self):
        """get_splits() returns configured splits for split pattern."""
        pattern = TransactionPattern(
            narration="TEST",
            splits=[
                AccountSplit(account="A", percentage=70),
                AccountSplit(account="B", percentage=30),
            ],
        )
        splits = pattern.get_splits()
        assert len(splits) == 2
        assert splits[0].account == "A"
        assert splits[1].account == "B"


class TestTransactionClassifierDefaults:
    """Tests for TransactionClassifier with default account and split percentage."""

    def test_default_account_for_unmatched(self):
        """Unmatched transactions go to default_account."""
        patterns = [
            TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        ]
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:Uncategorized",
        )
        # Matched transaction
        result = classifier.classify("SPOTIFY PREMIUM", Decimal("100"))
        assert result is not None
        assert len(result.splits) == 1
        assert result.splits[0].account == "Expenses:Music"

        # Unmatched transaction goes to default
        result = classifier.classify("RANDOM MERCHANT", Decimal("100"))
        assert result is not None
        assert len(result.splits) == 1
        assert result.splits[0].account == "Expenses:Uncategorized"
        assert result.splits[0].percentage == Decimal("100")

    def test_no_default_account_returns_none_for_unmatched(self):
        """Without default_account, unmatched transactions return None."""
        patterns = [
            TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        ]
        classifier = TransactionClassifier(patterns)
        result = classifier.classify("RANDOM MERCHANT", Decimal("100"))
        assert result is None

    def test_default_split_percentage_splits_matched(self):
        """default_split_percentage splits matched transactions."""
        patterns = [
            TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        ]
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("50"),
        )
        result = classifier.classify("SPOTIFY PREMIUM", Decimal("9.99"))
        assert result is not None
        assert len(result.splits) == 2
        # 50% to matched account
        assert result.splits[0].account == "Expenses:Music"
        assert result.splits[0].percentage == Decimal("50")
        # 50% to default/review account
        assert result.splits[1].account == "Expenses:NeedsReview"
        assert result.splits[1].percentage == Decimal("50")

    def test_default_split_percentage_with_pattern_splits(self):
        """default_split_percentage works with pattern that has splits."""
        patterns = [
            TransactionPattern(
                narration="COSTCO",
                splits=[
                    AccountSplit(account="Expenses:Groceries", percentage=80),
                    AccountSplit(account="Expenses:Household", percentage=20),
                ],
            )
        ]
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("50"),
        )
        result = classifier.classify("COSTCO WHOLESALE", Decimal("200"))
        assert result is not None
        assert len(result.splits) == 3
        # Pattern splits are scaled by (100 - 50) / 100 = 0.5
        # 80% * 0.5 = 40%
        assert result.splits[0].account == "Expenses:Groceries"
        assert result.splits[0].percentage == Decimal("40")
        # 20% * 0.5 = 10%
        assert result.splits[1].account == "Expenses:Household"
        assert result.splits[1].percentage == Decimal("10")
        # 50% to review
        assert result.splits[2].account == "Expenses:NeedsReview"
        assert result.splits[2].percentage == Decimal("50")

    def test_default_split_percentage_requires_default_account(self):
        """default_split_percentage requires default_account to be set."""
        with pytest.raises(ValueError):
            TransactionClassifier(
                [],
                default_split_percentage=Decimal("50"),
            )

    def test_zero_default_split_percentage(self):
        """default_split_percentage of 0 means 100% to matched account."""
        patterns = [
            TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        ]
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("0"),
        )
        result = classifier.classify("SPOTIFY PREMIUM", Decimal("9.99"))
        assert len(result.splits) == 2
        # 100% to matched
        assert result.splits[0].percentage == Decimal("100")
        # 0% to review
        assert result.splits[1].percentage == Decimal("0")

    def test_hundred_default_split_percentage(self):
        """default_split_percentage of 100 means 0% to matched, 100% to review."""
        patterns = [
            TransactionPattern(narration="SPOTIFY", account="Expenses:Music")
        ]
        classifier = TransactionClassifier(
            patterns,
            default_account="Expenses:NeedsReview",
            default_split_percentage=Decimal("100"),
        )
        result = classifier.classify("SPOTIFY PREMIUM", Decimal("9.99"))
        assert len(result.splits) == 2
        # 0% to matched
        assert result.splits[0].percentage == Decimal("0")
        # 100% to review
        assert result.splits[1].percentage == Decimal("100")

    def test_classify_returns_classification_result(self):
        """classify() returns ClassificationResult object."""
        patterns = [
            TransactionPattern(narration="TEST", account="Expenses:Test")
        ]
        classifier = TransactionClassifier(patterns)
        result = classifier.classify("TEST MERCHANT", Decimal("100"))
        assert isinstance(result, ClassificationResult)
        assert isinstance(result.splits, list)
        assert all(isinstance(s, AccountSplit) for s in result.splits)


class TestSharedExpense:
    """Tests for SharedExpense model."""

    def test_create_shared_expense(self):
        """Basic SharedExpense creation."""
        shared = SharedExpense(
            receivable_account="Assets:Receivables:Alex",
            offset_account="Income:Reimbursements",
            percentage=50,
        )
        assert shared.receivable_account == "Assets:Receivables:Alex"
        assert shared.offset_account == "Income:Reimbursements"
        assert shared.percentage == Decimal("50")

    def test_percentage_coercion(self):
        """Percentage can be int, float, or string."""
        shared_int = SharedExpense(
            receivable_account="A", offset_account="B", percentage=50
        )
        assert shared_int.percentage == Decimal("50")

        shared_float = SharedExpense(
            receivable_account="A", offset_account="B", percentage=33.33
        )
        assert shared_float.percentage == Decimal("33.33")

        shared_str = SharedExpense(
            receivable_account="A", offset_account="B", percentage="25"
        )
        assert shared_str.percentage == Decimal("25")

    def test_percentage_must_be_between_0_and_100(self):
        """Percentage must be in valid range."""
        with pytest.raises(ValidationError):
            SharedExpense(receivable_account="A", offset_account="B", percentage=-10)
        with pytest.raises(ValidationError):
            SharedExpense(receivable_account="A", offset_account="B", percentage=101)


class TestTransactionPatternSharedWith:
    """Tests for TransactionPattern with shared_with."""

    def test_pattern_with_shared_expense(self):
        """Pattern can specify shared_with for receivables tracking."""
        pattern = TransactionPattern(
            narration="REMA 1000",
            account="Expenses:Groceries",
            shared_with=[
                SharedExpense(
                    receivable_account="Assets:Receivables:Alex",
                    offset_account="Income:Reimbursements",
                    percentage=50,
                ),
            ],
        )
        assert pattern.shared_with is not None
        assert len(pattern.shared_with) == 1
        assert pattern.shared_with[0].receivable_account == "Assets:Receivables:Alex"

    def test_shared_with_percentage_cannot_exceed_100(self):
        """shared_with percentages cannot sum to more than 100."""
        with pytest.raises(ValidationError):
            TransactionPattern(
                narration="TEST",
                account="Expenses:Test",
                shared_with=[
                    SharedExpense(receivable_account="A", offset_account="B", percentage=60),
                    SharedExpense(receivable_account="C", offset_account="D", percentage=50),
                ],
            )

    def test_multiple_shared_expenses(self):
        """Pattern can have multiple shared expenses (sharing with multiple people)."""
        pattern = TransactionPattern(
            narration="RESTAURANT",
            account="Expenses:Dining",
            shared_with=[
                SharedExpense(
                    receivable_account="Assets:Receivables:Alex",
                    offset_account="Income:Reimbursements",
                    percentage=33,
                ),
                SharedExpense(
                    receivable_account="Assets:Receivables:Jordan",
                    offset_account="Income:Reimbursements",
                    percentage=33,
                ),
            ],
        )
        assert len(pattern.shared_with) == 2
        total = sum(s.percentage for s in pattern.shared_with)
        assert total == Decimal("66")

    def test_classify_includes_shared_with(self):
        """classify() returns shared_with in result."""
        patterns = [
            TransactionPattern(
                narration="GROCERIES",
                account="Expenses:Groceries",
                shared_with=[
                    SharedExpense(
                        receivable_account="Assets:Receivables:Alex",
                        offset_account="Income:Reimbursements",
                        percentage=50,
                    ),
                ],
            )
        ]
        classifier = TransactionClassifier(patterns)
        result = classifier.classify("GROCERIES STORE", Decimal("100"))

        assert result is not None
        assert result.shared_with is not None
        assert len(result.shared_with) == 1
        assert result.shared_with[0].percentage == Decimal("50")


class TestTransactionPatternFields:
    """Tests for field-based pattern matching."""

    def test_field_substring_match(self):
        """Field pattern matches substring by default."""
        pattern = TransactionPattern(
            fields={"to_account": "98712345678"},
            account="Assets:Bank:Savings",
        )
        assert pattern.matches("Any narration", Decimal("100"), {"to_account": "98712345678"}) is True
        assert pattern.matches("Any narration", Decimal("100"), {"to_account": "Transfer to 98712345678"}) is True
        assert pattern.matches("Any narration", Decimal("100"), {"to_account": "12345678"}) is False

    def test_field_regex_match(self):
        """Field pattern with regex matching."""
        pattern = TransactionPattern(
            fields={"merchant_code": r"5411|5412"},  # Grocery MCCs
            fields_regex=True,
            account="Expenses:Groceries",
        )
        assert pattern.matches("", Decimal("100"), {"merchant_code": "5411"}) is True
        assert pattern.matches("", Decimal("100"), {"merchant_code": "5412"}) is True
        assert pattern.matches("", Decimal("100"), {"merchant_code": "5413"}) is False

    def test_multiple_fields_all_must_match(self):
        """All field conditions must match (AND logic)."""
        pattern = TransactionPattern(
            fields={
                "transaction_type": "ATM",
                "location": "OSLO",
            },
            account="Expenses:Cash",
        )
        assert pattern.matches("", Decimal("100"), {"transaction_type": "ATM", "location": "OSLO"}) is True
        assert pattern.matches("", Decimal("100"), {"transaction_type": "ATM", "location": "BERGEN"}) is False
        assert pattern.matches("", Decimal("100"), {"transaction_type": "DEBIT", "location": "OSLO"}) is False

    def test_field_match_with_missing_field(self):
        """Missing field in input fails match."""
        pattern = TransactionPattern(
            fields={"to_account": "12345"},
            account="Assets:Bank",
        )
        # Field not present - should not match
        assert pattern.matches("", Decimal("100"), {"other_field": "value"}) is False
        # Empty field value - substring match of "12345" in "" fails
        assert pattern.matches("", Decimal("100"), {"to_account": ""}) is False

    def test_field_match_with_no_fields_provided(self):
        """Pattern with fields fails when no fields provided."""
        pattern = TransactionPattern(
            fields={"to_account": "12345"},
            account="Assets:Bank",
        )
        assert pattern.matches("", Decimal("100"), None) is False
        assert pattern.matches("", Decimal("100")) is False

    def test_combined_narration_and_fields(self):
        """Pattern with both narration and fields requires both to match."""
        pattern = TransactionPattern(
            narration="TRANSFER",
            fields={"to_account": "98712345678"},
            account="Assets:Bank:Savings",
        )
        # Both match
        assert pattern.matches("TRANSFER TO SAVINGS", Decimal("100"), {"to_account": "98712345678"}) is True
        # Only narration matches
        assert pattern.matches("TRANSFER TO SAVINGS", Decimal("100"), {"to_account": "other"}) is False
        # Only field matches
        assert pattern.matches("OTHER", Decimal("100"), {"to_account": "98712345678"}) is False

    def test_combined_amount_and_fields(self):
        """Pattern with both amount and fields requires both to match."""
        pattern = TransactionPattern(
            amount_condition=amount > 500,
            fields={"transaction_type": "ATM"},
            account="Expenses:Cash:Large",
        )
        # Both match
        assert pattern.matches("", Decimal("600"), {"transaction_type": "ATM"}) is True
        # Only amount matches
        assert pattern.matches("", Decimal("600"), {"transaction_type": "DEBIT"}) is False
        # Only field matches
        assert pattern.matches("", Decimal("100"), {"transaction_type": "ATM"}) is False

    def test_combined_narration_amount_and_fields(self):
        """Pattern with narration, amount, and fields requires all to match."""
        pattern = TransactionPattern(
            narration="VINMONOPOLET",
            amount_condition=amount > 500,
            fields={"store_id": "OSLO"},
            account="Expenses:Alcohol:Expensive:Oslo",
        )
        # All three match
        assert pattern.matches(
            "VINMONOPOLET GRUNERLOKKA",
            Decimal("750"),
            {"store_id": "OSLO"}
        ) is True
        # Narration doesn't match
        assert pattern.matches(
            "OTHER STORE",
            Decimal("750"),
            {"store_id": "OSLO"}
        ) is False
        # Amount doesn't match
        assert pattern.matches(
            "VINMONOPOLET GRUNERLOKKA",
            Decimal("100"),
            {"store_id": "OSLO"}
        ) is False
        # Field doesn't match
        assert pattern.matches(
            "VINMONOPOLET GRUNERLOKKA",
            Decimal("750"),
            {"store_id": "BERGEN"}
        ) is False

    def test_field_only_pattern_is_valid(self):
        """Pattern with only fields (no narration or amount) is valid."""
        pattern = TransactionPattern(
            fields={"to_account": "98712345678"},
            account="Assets:Bank:Savings",
        )
        assert pattern.fields is not None
        assert pattern.narration is None
        assert pattern.amount_condition is None

    def test_field_pattern_special_chars_escaped_by_default(self):
        """Special regex characters are escaped in non-regex field patterns."""
        pattern = TransactionPattern(
            fields={"note": "Amount (USD)"},
            account="Expenses:Foreign",
        )
        # Should match literally including parentheses
        assert pattern.matches("", Decimal("100"), {"note": "Amount (USD) 50"}) is True
        # Without escaping, parentheses would be regex group
        assert pattern.matches("", Decimal("100"), {"note": "Amount USD"}) is False


class TestTransactionClassifierWithFields:
    """Tests for TransactionClassifier with field-based patterns."""

    def test_classify_with_fields(self):
        """Classifier passes fields to pattern matching."""
        patterns = [
            TransactionPattern(
                fields={"to_account": "98712345678"},
                account="Assets:Bank:Savings",
            ),
            TransactionPattern(
                narration="FALLBACK",
                account="Expenses:Other",
            ),
        ]
        classifier = TransactionClassifier(patterns)

        # Field pattern matches
        result = classifier.classify("Any", Decimal("100"), {"to_account": "98712345678"})
        assert result is not None
        assert result.splits[0].account == "Assets:Bank:Savings"

        # Field pattern doesn't match, fallback narration doesn't match either
        result = classifier.classify("Any", Decimal("100"), {"to_account": "other"})
        assert result is None

        # Field pattern doesn't match, but fallback narration matches
        result = classifier.classify("FALLBACK TRANSACTION", Decimal("100"), {"to_account": "other"})
        assert result is not None
        assert result.splits[0].account == "Expenses:Other"

    def test_classify_field_pattern_with_no_fields(self):
        """Field patterns don't match when no fields provided."""
        patterns = [
            TransactionPattern(
                fields={"to_account": "12345"},
                account="Assets:Bank",
            ),
            TransactionPattern(
                narration="SPOTIFY",
                account="Expenses:Music",
            ),
        ]
        classifier = TransactionClassifier(patterns)

        # No fields - field pattern fails, narration pattern matches
        result = classifier.classify("SPOTIFY PREMIUM", Decimal("9.99"))
        assert result is not None
        assert result.splits[0].account == "Expenses:Music"

        # No fields and no narration match
        result = classifier.classify("UNKNOWN", Decimal("100"))
        assert result is None

    def test_first_matching_field_pattern_wins(self):
        """First matching pattern wins (order matters)."""
        patterns = [
            TransactionPattern(
                fields={"type": "ATM"},
                account="Expenses:Cash:ATM",
            ),
            TransactionPattern(
                fields={"type": "ATM"},
                amount_condition=amount > 500,
                account="Expenses:Cash:LargeATM",
            ),
        ]
        classifier = TransactionClassifier(patterns)

        # First pattern matches (even though second would too)
        result = classifier.classify("", Decimal("600"), {"type": "ATM"})
        assert result.splits[0].account == "Expenses:Cash:ATM"
