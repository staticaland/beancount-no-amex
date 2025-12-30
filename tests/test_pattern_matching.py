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

from beancount_no_amex.models import (
    AmountCondition,
    AmountOperator,
    TransactionPattern,
    amount_between,
    amount_eq,
    amount_gt,
    amount_gte,
    amount_lt,
    amount_lte,
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
        """At least one of narration or amount_condition must be specified."""
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


class TestAmountHelperFunctions:
    """Tests for the fluent API helper functions."""

    def test_amount_lt(self):
        """amount_lt creates correct AmountCondition."""
        condition = amount_lt(100)
        assert condition.operator == AmountOperator.LT
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("99")) is True
        assert condition.matches(Decimal("100")) is False

    def test_amount_lte(self):
        """amount_lte creates correct AmountCondition."""
        condition = amount_lte(100)
        assert condition.operator == AmountOperator.LTE
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("101")) is False

    def test_amount_gt(self):
        """amount_gt creates correct AmountCondition."""
        condition = amount_gt(100)
        assert condition.operator == AmountOperator.GT
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("101")) is True
        assert condition.matches(Decimal("100")) is False

    def test_amount_gte(self):
        """amount_gte creates correct AmountCondition."""
        condition = amount_gte(100)
        assert condition.operator == AmountOperator.GTE
        assert condition.value == Decimal("100")
        assert condition.matches(Decimal("100")) is True
        assert condition.matches(Decimal("99")) is False

    def test_amount_eq(self):
        """amount_eq creates correct AmountCondition."""
        condition = amount_eq(99.99)
        assert condition.operator == AmountOperator.EQ
        assert condition.value == Decimal("99.99")
        assert condition.matches(Decimal("99.99")) is True
        assert condition.matches(Decimal("100")) is False

    def test_amount_between(self):
        """amount_between creates correct AmountCondition."""
        condition = amount_between(50, 100)
        assert condition.operator == AmountOperator.BETWEEN
        assert condition.value == Decimal("50")
        assert condition.value2 == Decimal("100")
        assert condition.matches(Decimal("75")) is True
        assert condition.matches(Decimal("49")) is False

    def test_helpers_accept_various_types(self):
        """Helper functions accept int, float, string, and Decimal."""
        # Integer
        assert amount_lt(100).value == Decimal("100")
        # Float
        assert amount_lt(99.99).value == Decimal("99.99")
        # String
        assert amount_lt("50.50").value == Decimal("50.50")
        # Decimal
        assert amount_lt(Decimal("25")).value == Decimal("25")

    def test_helpers_in_transaction_pattern(self):
        """Helper functions work seamlessly with TransactionPattern."""
        pattern = TransactionPattern(
            narration="TEST",
            amount_condition=amount_gt(500),
            account="Expenses:Large",
        )
        assert pattern.matches("TEST MERCHANT", Decimal("600")) is True
        assert pattern.matches("TEST MERCHANT", Decimal("400")) is False
