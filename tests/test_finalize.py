"""Component tests for transaction finalization (finalize method).

The finalize() method applies categorization rules to transactions:
- Matches narration text against configured patterns
- Adds a balancing posting to the matched expense account
- Returns the transaction unchanged if no pattern matches
"""

from decimal import Decimal

import pytest
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D

from beancount_no_amex.credit import AmexAccountConfig, Importer
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
            narration_to_account_mappings=[
                ("REMA", "Expenses:Groceries:Supermarket"),
                ("REMA 1000", "Expenses:Groceries:Rema"),  # More specific but second
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
