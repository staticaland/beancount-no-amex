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
from beancount_no_amex.classify import AccountSplit, SharedExpense, TransactionPattern, amount
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


class TestFinalizeSplitTransactions:
    """Tests for split transaction functionality in finalize."""

    @pytest.fixture
    def importer_with_splits(self):
        """Importer with split transaction patterns."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(
                    narration="COSTCO",
                    splits=[
                        AccountSplit(account="Expenses:Groceries", percentage=80),
                        AccountSplit(account="Expenses:Household", percentage=20),
                    ],
                ),
                TransactionPattern(narration="SPOTIFY", account="Expenses:Music"),
            ],
        )
        return Importer(config=config, debug=False)

    def test_split_creates_multiple_postings(self, importer_with_splits):
        """Split pattern creates multiple balancing postings."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="COSTCO WHOLESALE",
            narration="COSTCO WHOLESALE",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_splits.finalize(txn, RawTransaction())

        # Should have 3 postings: original + 2 splits
        assert len(result.postings) == 3
        # First posting is the original
        assert result.postings[0].account == "Liabilities:CreditCard:Amex"
        assert result.postings[0].units.number == D("-100.00")
        # Second posting is 80% of 100 = 80
        assert result.postings[1].account == "Expenses:Groceries"
        assert result.postings[1].units.number == D("80.00")
        # Third posting is 20% of 100 = 20
        assert result.postings[2].account == "Expenses:Household"
        assert result.postings[2].units.number == D("20.00")

    def test_split_with_odd_amount(self, importer_with_splits):
        """Split handles amounts that don't divide evenly."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-123.45"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="COSTCO",
            narration="COSTCO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_splits.finalize(txn, RawTransaction())

        # 80% of 123.45 = 98.76
        assert result.postings[1].units.number == D("98.76")
        # 20% of 123.45 = 24.69
        assert result.postings[2].units.number == D("24.69")

    def test_single_account_pattern_still_works(self, importer_with_splits):
        """Single account patterns work alongside split patterns."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-9.99"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="SPOTIFY PREMIUM",
            narration="SPOTIFY PREMIUM",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_splits.finalize(txn, RawTransaction())

        # Single account = 2 postings (original + balancing)
        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Music"
        assert result.postings[1].units.number == D("9.99")


class TestFinalizeDefaultAccount:
    """Tests for default account functionality in finalize."""

    @pytest.fixture
    def importer_with_default(self):
        """Importer with default_account configured."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            default_account="Expenses:Uncategorized",
            transaction_patterns=[
                TransactionPattern(narration="SPOTIFY", account="Expenses:Music"),
            ],
        )
        return Importer(config=config, debug=False)

    def test_unmatched_goes_to_default(self, importer_with_default):
        """Unmatched transactions go to default_account."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-50.00"), "NOK"),
            None, None, None, None,
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

        result = importer_with_default.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Uncategorized"
        assert result.postings[1].units.number == D("50.00")

    def test_matched_still_uses_pattern(self, importer_with_default):
        """Matched transactions still use pattern account, not default."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-9.99"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="SPOTIFY",
            narration="SPOTIFY",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_default.finalize(txn, RawTransaction())

        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:Music"


class TestFinalizeDefaultSplitPercentage:
    """Tests for default_split_percentage functionality in finalize."""

    @pytest.fixture
    def importer_with_review_split(self):
        """Importer with default_split_percentage for review workflow."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            default_account="Expenses:NeedsReview",
            default_split_percentage=50,  # 50% confidence
            transaction_patterns=[
                TransactionPattern(narration="SPOTIFY", account="Expenses:Music"),
            ],
        )
        return Importer(config=config, debug=False)

    def test_matched_splits_with_default_percentage(self, importer_with_review_split):
        """Matched transactions are split between pattern and review account."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="SPOTIFY",
            narration="SPOTIFY",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_review_split.finalize(txn, RawTransaction())

        # 3 postings: original + 50% pattern + 50% review
        assert len(result.postings) == 3
        assert result.postings[1].account == "Expenses:Music"
        assert result.postings[1].units.number == D("50.00")
        assert result.postings[2].account == "Expenses:NeedsReview"
        assert result.postings[2].units.number == D("50.00")

    def test_unmatched_goes_fully_to_default(self, importer_with_review_split):
        """Unmatched transactions go 100% to default_account."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="UNKNOWN",
            narration="UNKNOWN",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_review_split.finalize(txn, RawTransaction())

        # Unmatched = 100% to default
        assert len(result.postings) == 2
        assert result.postings[1].account == "Expenses:NeedsReview"
        assert result.postings[1].units.number == D("100.00")

    @pytest.fixture
    def importer_with_split_and_review(self):
        """Importer with pattern splits AND default_split_percentage."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            default_account="Expenses:NeedsReview",
            default_split_percentage=50,
            transaction_patterns=[
                TransactionPattern(
                    narration="COSTCO",
                    splits=[
                        AccountSplit(account="Expenses:Groceries", percentage=80),
                        AccountSplit(account="Expenses:Household", percentage=20),
                    ],
                ),
            ],
        )
        return Importer(config=config, debug=False)

    def test_pattern_splits_combined_with_review_split(self, importer_with_split_and_review):
        """Pattern splits are scaled down when combined with review split."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="COSTCO",
            narration="COSTCO",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer_with_split_and_review.finalize(txn, RawTransaction())

        # 4 postings: original + scaled groceries + scaled household + review
        assert len(result.postings) == 4
        # 80% * 50% = 40%
        assert result.postings[1].account == "Expenses:Groceries"
        assert result.postings[1].units.number == D("40.00")
        # 20% * 50% = 10%
        assert result.postings[2].account == "Expenses:Household"
        assert result.postings[2].units.number == D("10.00")
        # 50% review
        assert result.postings[3].account == "Expenses:NeedsReview"
        assert result.postings[3].units.number == D("50.00")


class TestFinalizeSharedExpenses:
    """Tests for shared expense / receivables tracking in finalize."""

    @pytest.fixture
    def importer_with_shared_expense(self):
        """Importer with shared expense patterns."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(
                    narration="REMA 1000",
                    account="Expenses:Groceries",
                    shared_with=[
                        SharedExpense(
                            receivable_account="Assets:Receivables:Alex",
                            offset_account="Income:Reimbursements",
                            percentage=50,
                        ),
                    ],
                ),
            ],
        )
        return Importer(config=config, debug=False)

    def test_shared_expense_creates_four_postings(self, importer_with_shared_expense):
        """Shared expense creates 4 postings: CC, expense, receivable, offset."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-400.00"), "NOK"),
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

        result = importer_with_shared_expense.finalize(txn, RawTransaction())

        # 4 postings: CC + expense + receivable + offset
        assert len(result.postings) == 4

        # 1. Credit card (original)
        assert result.postings[0].account == "Liabilities:CreditCard:Amex"
        assert result.postings[0].units.number == D("-400.00")

        # 2. Expense (full amount - shows true household spend)
        assert result.postings[1].account == "Expenses:Groceries"
        assert result.postings[1].units.number == D("400.00")

        # 3. Receivable (50% - tracks what Alex owes)
        assert result.postings[2].account == "Assets:Receivables:Alex"
        assert result.postings[2].units.number == D("200.00")

        # 4. Offset (negative 50% - reduces your net expense)
        assert result.postings[3].account == "Income:Reimbursements"
        assert result.postings[3].units.number == D("-200.00")

    def test_shared_expense_with_multiple_people(self):
        """Sharing with multiple people creates multiple receivable/offset pairs."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            transaction_patterns=[
                TransactionPattern(
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
                ),
            ],
        )
        importer = Importer(config=config, debug=False)

        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-300.00"), "NOK"),
            None, None, None, None,
        )
        txn = data.Transaction(
            meta=meta,
            date=None,
            flag="*",
            payee="RESTAURANT",
            narration="RESTAURANT DOWNTOWN",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[primary_posting],
        )

        result = importer.finalize(txn, RawTransaction())

        # 6 postings: CC + expense + 2x(receivable + offset)
        assert len(result.postings) == 6

        # Expense is still full amount
        assert result.postings[1].account == "Expenses:Dining"
        assert result.postings[1].units.number == D("300.00")

        # Alex's share: 33% of 300 = 99
        assert result.postings[2].account == "Assets:Receivables:Alex"
        assert result.postings[2].units.number == D("99.00")
        assert result.postings[3].account == "Income:Reimbursements"
        assert result.postings[3].units.number == D("-99.00")

        # Jordan's share: 33% of 300 = 99
        assert result.postings[4].account == "Assets:Receivables:Jordan"
        assert result.postings[4].units.number == D("99.00")
        assert result.postings[5].account == "Income:Reimbursements"
        assert result.postings[5].units.number == D("-99.00")

    def test_shared_expense_preserves_currency(self, importer_with_shared_expense):
        """Shared expense postings preserve the original currency."""
        meta = data.new_metadata("test.qbo", 1)
        primary_posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100.00"), "USD"),  # Different currency
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

        result = importer_with_shared_expense.finalize(txn, RawTransaction())

        # All postings should use USD
        for posting in result.postings:
            assert posting.units.currency == "USD"
