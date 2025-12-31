"""Component tests for transaction finalization (finalize method).

The finalize() method applies categorization rules to transactions:
- Matches narration text against configured patterns (substring or regex)
- Matches transactions by amount conditions (lt, lte, gt, gte, eq, between)
- Adds a balancing posting to the matched expense account
- Returns the transaction unchanged if no pattern matches
"""

from decimal import Decimal

import pytest
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D

from beancount_no_amex.credit import AmexAccountConfig, Importer
from beancount_no_amex.classify import TransactionPattern, amount
from beancount_no_amex.models import RawTransaction


class TestFinalizeBasics:
    """Basic finalization/categorization tests."""

    def test_adds_balancing_posting_when_pattern_matches(self, importer_with_mappings):
        """When narration matches a pattern, adds balancing posting."""
        # Create a transaction with VINMONOPOLET in narration
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-742.18"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="VINMONOPOLET GRUNERLOKKA",
            narration="VINMONOPOLET GRUNERLOKKA",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # Should have two postings now
        assert len(result.postings) == 2
        # Second posting should be to Expenses:Groceries
        assert result.postings[1].account == "Expenses:Groceries"
        # Amount should be opposite (positive)
        assert result.postings[1].units.number == D("742.18")

    def test_returns_unchanged_when_no_pattern_matches(self, importer_with_mappings):
        """Transaction unchanged when narration doesn't match any pattern."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-50.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="UNKNOWN MERCHANT",
            narration="UNKNOWN MERCHANT",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # Should still have only one posting
        assert len(result.postings) == 1
        assert result == txn

    def test_no_mappings_returns_unchanged(self, basic_importer):
        """Importer with no mappings returns transaction unchanged."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="ANY MERCHANT",
            narration="ANY MERCHANT",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = basic_importer.finalize(txn, RawTransaction())

        assert len(result.postings) == 1
        assert result == txn


class TestFinalizePatternMatching:
    """Tests for pattern matching behavior."""

    def test_case_sensitive_matching(self, importer_with_mappings):
        """Pattern matching is case-sensitive."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-50.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        # Lowercase "vinmonopolet" won't match "VINMONOPOLET"
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="vinmonopolet lowercase",
            narration="vinmonopolet lowercase",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # No match - only one posting
        assert len(result.postings) == 1

    def test_partial_match_works(self, importer_with_mappings):
        """Pattern can match anywhere in the narration."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-99.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        # "SPOTIFY" is in the middle of the narration
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="Premium SPOTIFY Subscription",
            narration="Premium SPOTIFY Subscription",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Entertainment:Music"

    def test_first_matching_pattern_wins(self):
        """First matching pattern is used (order matters)."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(narration="REMA", account="Expenses:Groceries:Supermarket"),
                TransactionPattern(narration="REMA 1000", account="Expenses:Groceries:Rema"),
            ],
        )
        importer = Importer(config=config, debug=False)

        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-200.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="REMA 1000 OSLO",
            narration="REMA 1000 OSLO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer.finalize(txn, RawTransaction())

        # First pattern ("REMA") matches first
        assert result.postings[1].account == "Expenses:Groceries:Supermarket"


class TestFinalizeAmountHandling:
    """Tests for amount handling in balancing postings."""

    def test_debit_creates_positive_balance(self, importer_with_mappings):
        """Debit (negative amount) creates positive balancing posting."""
        meta = data.new_metadata("test.qbo", 1)
        # Debit is negative on credit card
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-500.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="KIWI STORE",
            narration="KIWI STORE",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # Expense posting should be positive
        assert result.postings[1].units.number == D("500.00")

    def test_credit_creates_negative_balance(self, importer_with_mappings):
        """Credit (positive amount) creates negative balancing posting."""
        meta = data.new_metadata("test.qbo", 1)
        # Refund is positive on credit card
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("100.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="NETFLIX REFUND",
            narration="NETFLIX REFUND",  # Matches NETFLIX pattern
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # Expense posting should be negative (refund)
        assert result.postings[1].units.number == D("-100.00")

    def test_currency_preserved_in_balancing_posting(self, importer_with_mappings):
        """Currency is preserved in the balancing posting."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-50.00"), "USD"),  # Different currency
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="REMA INTERNATIONAL",
            narration="REMA INTERNATIONAL",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        assert result.postings[1].units.currency == "USD"


class TestFinalizeEdgeCases:
    """Edge cases for finalization."""

    def test_empty_narration(self, importer_with_mappings):
        """Empty narration doesn't match any patterns."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-50.00"), "NOK"),
            None,
            None,
            None,
            None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee=None,
            narration="",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        assert len(result.postings) == 1

    def test_transaction_with_no_postings(self, importer_with_mappings):
        """Transaction with no postings is returned unchanged."""
        meta = data.new_metadata("test.qbo", 1)
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="VINMONOPOLET",
            narration="VINMONOPOLET",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[],  # Empty postings list
        )

        result = importer_with_mappings.finalize(txn, RawTransaction())

        # Should return unchanged (no postings to balance)
        assert result == txn
        assert len(result.postings) == 0


class TestFinalizeTransactionPatterns:
    """Tests for transaction_patterns matching."""

    @pytest.fixture
    def importer_with_patterns(self):
        """Importer with transaction_patterns configured."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(
                    narration=r"REMA\s*1000",
                    regex=True,
                    case_insensitive=True,
                    account="Expenses:Groceries:Rema",
                ),
                TransactionPattern(amount_condition=amount < 50, account="Expenses:PettyCash"),
                TransactionPattern(
                    narration="VINMONOPOLET",
                    amount_condition=amount > 500,
                    account="Expenses:Alcohol:Expensive",
                ),
            ],
        )
        return Importer(config=config, debug=False)

    def test_regex_pattern_matches(self, importer_with_patterns):
        """Regex pattern in transaction_patterns matches correctly."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-250.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="REMA 1000 OSLO",
            narration="REMA 1000 OSLO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Groceries:Rema"
        assert result.postings[1].units.number == D("250.00")

    def test_case_insensitive_pattern_matches(self, importer_with_patterns):
        """Case-insensitive pattern matches regardless of case."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-150.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="rema1000 store",
            narration="rema1000 store",  # lowercase
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Groceries:Rema"

    def test_amount_only_pattern_matches(self, importer_with_patterns):
        """Pattern with only amount condition matches based on amount."""
        meta = data.new_metadata("test.qbo", 1)
        # Small purchase under 50
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-25.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="UNKNOWN MERCHANT",
            narration="UNKNOWN MERCHANT",  # Doesn't match any narration pattern
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:PettyCash"

    def test_combined_pattern_requires_both(self, importer_with_patterns):
        """Combined pattern requires BOTH narration and amount to match."""
        meta = data.new_metadata("test.qbo", 1)

        # Matches narration but not amount (under 500)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-200.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="VINMONOPOLET OSLO",
            narration="VINMONOPOLET OSLO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        # Should NOT match (amount too low), falls through to amount-only pattern
        # But 200 is >= 50, so no match at all
        assert len(result.postings) == 1

    def test_combined_pattern_matches_when_both_conditions_met(self, importer_with_patterns):
        """Combined pattern matches when both narration and amount match."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-750.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="VINMONOPOLET OSLO",
            narration="VINMONOPOLET OSLO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Alcohol:Expensive"

    def test_first_matching_pattern_wins(self, importer_with_patterns):
        """First matching pattern is used (order matters)."""
        meta = data.new_metadata("test.qbo", 1)
        # Small REMA purchase - matches both regex and amount patterns
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-30.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="REMA 1000",
            narration="REMA 1000",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_patterns.finalize(txn, RawTransaction())

        # REMA pattern is first, so it wins
        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Groceries:Rema"


class TestFinalizeAmountConditions:
    """Tests for amount condition operators in finalize."""

    @pytest.fixture
    def importer_with_amount_patterns(self):
        """Importer with amount-based patterns."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(amount_condition=amount == 99, account="Expenses:Subscriptions"),
                TransactionPattern(amount_condition=amount.between(100, 500), account="Expenses:MediumPurchases"),
            ],
        )
        return Importer(config=config, debug=False)

    def test_exact_amount_matches(self, importer_with_amount_patterns):
        """Exact amount (==) pattern matches."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-99.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="ANY SERVICE",
            narration="ANY SERVICE",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_amount_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Subscriptions"

    def test_between_amount_matches(self, importer_with_amount_patterns):
        """Amount range (between) pattern matches."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-250.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="SOME STORE",
            narration="SOME STORE",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_amount_patterns.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:MediumPurchases"
