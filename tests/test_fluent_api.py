"""Tests for the fluent classification API.

These tests verify the "classification for humans" API:
    match("SPOTIFY") >> "Expenses:Music"
    when(amount < 50) >> "Expenses:PettyCash"
    field(to_account="12345") >> "Assets:Savings"
"""

from decimal import Decimal

import pytest

from beancount_classifier import (
    match,
    when,
    field,
    shared,
    amount,
    TransactionClassifier,
    TransactionPattern,
)
from beancount_classifier.classify import _PatternResult


class TestMatchFunction:
    """Tests for the match() factory function."""

    def test_simple_match(self):
        """Basic substring matching with match() >> account."""
        result = match("SPOTIFY") >> "Expenses:Music"
        assert isinstance(result, _PatternResult)

        pattern = result.pattern
        assert pattern.narration == "SPOTIFY"
        assert pattern.account == "Expenses:Music"
        assert pattern.regex is False
        assert pattern.case_insensitive is False

    def test_match_with_regex(self):
        """Regex matching with .regex property."""
        result = match(r"REMA\s*1000").regex >> "Expenses:Groceries"
        pattern = result.pattern

        assert pattern.narration == r"REMA\s*1000"
        assert pattern.regex is True
        assert pattern.account == "Expenses:Groceries"

    def test_match_with_ignorecase(self):
        """Case-insensitive matching with .ignorecase property."""
        result = match("spotify").ignorecase >> "Expenses:Music"
        pattern = result.pattern

        assert pattern.narration == "spotify"
        assert pattern.case_insensitive is True

    def test_match_with_short_i_alias(self):
        """Short .i alias for ignorecase."""
        result = match("spotify").i >> "Expenses:Music"
        pattern = result.pattern

        assert pattern.case_insensitive is True

    def test_match_with_regex_and_ignorecase(self):
        """Chaining .regex and .ignorecase."""
        result = match(r"rema\s*1000").regex.ignorecase >> "Expenses:Groceries"
        pattern = result.pattern

        assert pattern.regex is True
        assert pattern.case_insensitive is True

    def test_match_with_where_amount(self):
        """Combining narration and amount condition with .where()."""
        result = match("VINMONOPOLET").where(amount > 500) >> "Expenses:Alcohol"
        pattern = result.pattern

        assert pattern.narration == "VINMONOPOLET"
        assert pattern.amount_condition is not None
        assert pattern.amount_condition.value == Decimal("500")

    def test_match_with_splits(self):
        """Split across multiple accounts with tuple syntax."""
        result = match("COSTCO") >> [
            ("Expenses:Groceries", 80),
            ("Expenses:Household", 20),
        ]
        pattern = result.pattern

        assert pattern.splits is not None
        assert len(pattern.splits) == 2
        assert pattern.splits[0].account == "Expenses:Groceries"
        assert pattern.splits[0].percentage == Decimal("80")
        assert pattern.splits[1].account == "Expenses:Household"
        assert pattern.splits[1].percentage == Decimal("20")

    def test_match_with_float_percentages(self):
        """Split percentages can be floats."""
        result = match("STORE") >> [
            ("Expenses:A", 33.33),
            ("Expenses:B", 66.67),
        ]
        pattern = result.pattern

        assert pattern.splits[0].percentage == Decimal("33.33")
        assert pattern.splits[1].percentage == Decimal("66.67")


class TestWhenFunction:
    """Tests for the when() factory function (amount-only patterns)."""

    def test_when_less_than(self):
        """Amount less than condition."""
        result = when(amount < 50) >> "Expenses:PettyCash"
        pattern = result.pattern

        assert pattern.narration is None
        assert pattern.amount_condition is not None
        assert pattern.amount_condition.value == Decimal("50")
        assert pattern.account == "Expenses:PettyCash"

    def test_when_greater_than(self):
        """Amount greater than condition."""
        result = when(amount > 1000) >> "Expenses:Large"
        pattern = result.pattern

        assert pattern.amount_condition.value == Decimal("1000")

    def test_when_between(self):
        """Amount between condition."""
        result = when(amount.between(100, 500)) >> "Expenses:Medium"
        pattern = result.pattern

        assert pattern.amount_condition.value == Decimal("100")
        assert pattern.amount_condition.value2 == Decimal("500")

    def test_when_with_splits(self):
        """when() with split accounts."""
        result = when(amount > 500) >> [
            ("Expenses:Large", 90),
            ("Expenses:Review", 10),
        ]
        pattern = result.pattern

        assert pattern.splits is not None
        assert len(pattern.splits) == 2

    def test_when_requires_amount_condition(self):
        """when() must receive an AmountCondition."""
        with pytest.raises(TypeError, match="amount condition"):
            when("not a condition")


class TestFieldFunction:
    """Tests for the field() factory function."""

    def test_field_single(self):
        """Single field matching."""
        result = field(to_account="98712345678") >> "Assets:Savings"
        pattern = result.pattern

        assert pattern.fields == {"to_account": "98712345678"}
        assert pattern.account == "Assets:Savings"

    def test_field_multiple(self):
        """Multiple field matching (AND logic)."""
        result = field(type="ATM", location="Oslo") >> "Expenses:Cash"
        pattern = result.pattern

        assert pattern.fields == {"type": "ATM", "location": "Oslo"}

    def test_field_with_regex(self):
        """Field matching with regex patterns."""
        result = field(merchant_code=r"5411|5412").regex >> "Expenses:Groceries"
        pattern = result.pattern

        assert pattern.fields_regex is True

    def test_field_with_splits(self):
        """field() with split accounts."""
        result = field(type="TRANSFER") >> [
            ("Assets:Savings", 80),
            ("Assets:Emergency", 20),
        ]
        pattern = result.pattern

        assert pattern.splits is not None

    def test_field_requires_argument(self):
        """field() requires at least one field."""
        with pytest.raises(ValueError, match="requires at least one"):
            field()

    def test_match_where_field(self):
        """Combining match() with field() using .where()."""
        result = match("TRANSFER").where(field(to_account="12345")) >> "Assets:Savings"
        pattern = result.pattern

        assert pattern.narration == "TRANSFER"
        assert pattern.fields == {"to_account": "12345"}


class TestSharedFunction:
    """Tests for the shared() helper and | operator."""

    def test_shared_basic(self):
        """Basic shared expense with | operator."""
        result = match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50)
        pattern = result.pattern

        assert pattern.shared_with is not None
        assert len(pattern.shared_with) == 1
        assert pattern.shared_with[0].receivable_account == "Assets:Receivables:Alex"
        assert pattern.shared_with[0].percentage == Decimal("50")
        assert pattern.shared_with[0].offset_account == "Income:Reimbursements"

    def test_shared_custom_offset(self):
        """Shared expense with custom offset account."""
        result = match("RENT") >> "Expenses:Rent" | shared(
            "Assets:Receivables:Roommate",
            50,
            offset="Income:RentSplit"
        )
        pattern = result.pattern

        assert pattern.shared_with[0].offset_account == "Income:RentSplit"

    def test_shared_multiple(self):
        """Multiple shared expenses (multiple roommates)."""
        result = (
            match("DINNER") >> "Expenses:Dining"
            | shared("Assets:Receivables:Alex", 33)
            | shared("Assets:Receivables:Sam", 33)
        )
        pattern = result.pattern

        assert len(pattern.shared_with) == 2
        assert pattern.shared_with[0].receivable_account == "Assets:Receivables:Alex"
        assert pattern.shared_with[1].receivable_account == "Assets:Receivables:Sam"

    def test_shared_with_wrong_type(self):
        """| operator requires shared() result."""
        result = match("TEST") >> "Expenses:Test"
        with pytest.raises(TypeError, match="use shared()"):
            result | "not a shared spec"


class TestPatternActuallyWorks:
    """Tests that fluent patterns actually match transactions correctly."""

    def test_match_pattern_matches(self):
        """Fluent pattern correctly matches transactions."""
        result = match("SPOTIFY") >> "Expenses:Music"
        pattern = result.pattern

        assert pattern.matches("SPOTIFY Premium", Decimal("9.99")) is True
        assert pattern.matches("Netflix", Decimal("9.99")) is False

    def test_regex_pattern_matches(self):
        """Regex pattern correctly matches."""
        result = match(r"REMA\s*1000").regex >> "Expenses:Groceries"
        pattern = result.pattern

        assert pattern.matches("REMA 1000", Decimal("100")) is True
        assert pattern.matches("REMA1000", Decimal("100")) is True
        assert pattern.matches("KIWI", Decimal("100")) is False

    def test_ignorecase_pattern_matches(self):
        """Case-insensitive pattern correctly matches."""
        result = match("spotify").ignorecase >> "Expenses:Music"
        pattern = result.pattern

        assert pattern.matches("SPOTIFY", Decimal("10")) is True
        assert pattern.matches("Spotify", Decimal("10")) is True
        assert pattern.matches("spotify", Decimal("10")) is True

    def test_amount_condition_matches(self):
        """Amount condition correctly filters."""
        result = match("STORE").where(amount > 100) >> "Expenses:Large"
        pattern = result.pattern

        assert pattern.matches("STORE", Decimal("150")) is True
        assert pattern.matches("STORE", Decimal("50")) is False

    def test_field_pattern_matches(self):
        """Field pattern correctly matches."""
        result = field(type="ATM") >> "Expenses:Cash"
        pattern = result.pattern

        assert pattern.matches("Withdrawal", Decimal("100"), fields={"type": "ATM"}) is True
        assert pattern.matches("Withdrawal", Decimal("100"), fields={"type": "POS"}) is False


class TestTransactionClassifierIntegration:
    """Tests that fluent patterns work with TransactionClassifier."""

    def test_classifier_with_fluent_patterns(self):
        """TransactionClassifier accepts fluent patterns."""
        rules = [
            match("SPOTIFY") >> "Expenses:Music",
            match("NETFLIX") >> "Expenses:Entertainment",
            when(amount < 50) >> "Expenses:PettyCash",
        ]

        classifier = TransactionClassifier(rules)

        result = classifier.classify("SPOTIFY Premium", Decimal("9.99"))
        assert result.splits[0].account == "Expenses:Music"

        result = classifier.classify("NETFLIX", Decimal("15.99"))
        assert result.splits[0].account == "Expenses:Entertainment"

        result = classifier.classify("Coffee", Decimal("4.50"))
        assert result.splits[0].account == "Expenses:PettyCash"

    def test_classifier_with_default_alias(self):
        """TransactionClassifier accepts 'default' as alias for default_account."""
        rules = [match("SPOTIFY") >> "Expenses:Known"]
        classifier = TransactionClassifier(rules, default="Expenses:Uncategorized")

        result = classifier.classify("RANDOM MERCHANT", Decimal("100"))
        assert result.splits[0].account == "Expenses:Uncategorized"

    def test_classifier_mixed_patterns(self):
        """Classifier accepts both fluent and traditional patterns."""
        rules = [
            match("SPOTIFY") >> "Expenses:Music",
            TransactionPattern(narration="NETFLIX", account="Expenses:Entertainment"),
        ]

        classifier = TransactionClassifier(rules)

        result = classifier.classify("SPOTIFY", Decimal("10"))
        assert result.splits[0].account == "Expenses:Music"

        result = classifier.classify("NETFLIX", Decimal("10"))
        assert result.splits[0].account == "Expenses:Entertainment"

    def test_classifier_with_splits(self):
        """Classifier handles split patterns correctly."""
        rules = [
            match("COSTCO") >> [
                ("Expenses:Groceries", 80),
                ("Expenses:Household", 20),
            ]
        ]

        classifier = TransactionClassifier(rules)
        result = classifier.classify("COSTCO WHOLESALE", Decimal("200"))

        assert len(result.splits) == 2
        assert result.splits[0].account == "Expenses:Groceries"
        assert result.splits[0].percentage == Decimal("80")

    def test_classifier_with_shared_expenses(self):
        """Classifier handles shared expense patterns correctly."""
        rules = [
            match("GROCERIES") >> "Expenses:Groceries" | shared("Assets:Receivables:Alex", 50)
        ]

        classifier = TransactionClassifier(rules)
        result = classifier.classify("GROCERIES STORE", Decimal("100"))

        assert result.splits[0].account == "Expenses:Groceries"
        assert result.shared_with is not None
        assert len(result.shared_with) == 1
        assert result.shared_with[0].percentage == Decimal("50")


class TestFluentApiImports:
    """Tests that the fluent API is properly exported."""

    def test_top_level_imports(self):
        """All fluent API components are importable from top level."""
        from beancount_no_amex import match, when, field, shared, amount

        assert callable(match)
        assert callable(when)
        assert callable(field)
        assert callable(shared)
        assert hasattr(amount, '__lt__')

    def test_classifier_module_imports(self):
        """All fluent API components are importable from beancount_classifier."""
        from beancount_classifier import match, when, field, shared, amount

        assert callable(match)
        assert callable(when)
        assert callable(field)
        assert callable(shared)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_target_type(self):
        """>> operator requires string or list of tuples."""
        with pytest.raises(TypeError):
            match("TEST") >> 123

    def test_invalid_when_argument(self):
        """when() requires AmountCondition."""
        with pytest.raises(TypeError):
            when("invalid")

    def test_empty_field_call(self):
        """field() requires at least one argument."""
        with pytest.raises(ValueError):
            field()

    def test_chaining_returns_new_builder(self):
        """Chaining methods returns new builder, not modifying original."""
        base = match("TEST")
        with_regex = base.regex
        with_ignorecase = base.ignorecase

        # Base should be unchanged
        assert base._is_regex is False
        assert base._ignore_case is False

        # Each chain produces independent result
        assert with_regex._is_regex is True
        assert with_regex._ignore_case is False

        assert with_ignorecase._is_regex is False
        assert with_ignorecase._ignore_case is True
