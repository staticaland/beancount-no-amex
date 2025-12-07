"""Unit tests for data models (models.py).

These tests verify the Pydantic data models that represent each stage
of the data transformation pipeline:

    RawTransaction → ParsedTransaction → BeanTransaction

Each model adds validation and type safety to the pipeline.
"""

import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from beancount_no_amex.models import (
    BeanTransaction,
    ParsedTransaction,
    QboFileData,
    RawTransaction,
)


# =============================================================================
# RawTransaction Tests (Stage 1: Raw XML extraction)
# =============================================================================


class TestRawTransaction:
    """Tests for RawTransaction - the first stage of data extraction.

    RawTransaction holds strings exactly as they appear in the QBO XML.
    All fields are optional because QBO files may have missing data.
    """

    def test_create_complete_transaction(self, raw_transaction_debit):
        """A complete transaction has all fields populated."""
        assert raw_transaction_debit.date == "20250320000000.000[-7:MST]"
        assert raw_transaction_debit.amount == "-742.18"
        assert raw_transaction_debit.payee == "VINMONOPOLET GRUNERLOKKA OSLO"
        assert raw_transaction_debit.memo == "LINA HANSEN-81023"
        assert raw_transaction_debit.id == "AT250800024000010012345"
        assert raw_transaction_debit.type == "DEBIT"

    def test_create_minimal_transaction(self):
        """Minimal transaction with only date and amount."""
        txn = RawTransaction(date="20250320", amount="-50.00")
        assert txn.date == "20250320"
        assert txn.amount == "-50.00"
        assert txn.payee is None
        assert txn.memo is None

    def test_create_empty_transaction(self):
        """All fields can be None - QBO files may have sparse data."""
        txn = RawTransaction()
        assert txn.date is None
        assert txn.amount is None
        assert txn.payee is None

    def test_credit_vs_debit_types(self, raw_transaction_debit, raw_transaction_credit):
        """Transaction types distinguish charges from refunds/payments."""
        assert raw_transaction_debit.type == "DEBIT"
        assert raw_transaction_credit.type == "CREDIT"

    def test_amount_stored_as_string(self):
        """Amounts remain as strings - parsing happens in next stage."""
        txn = RawTransaction(amount="-1234.56")
        assert isinstance(txn.amount, str)
        assert txn.amount == "-1234.56"


# =============================================================================
# ParsedTransaction Tests (Stage 2: Typed and validated)
# =============================================================================


class TestParsedTransaction:
    """Tests for ParsedTransaction - validated and typed data.

    This stage converts strings to proper Python types:
    - date string → datetime.date
    - amount string → Decimal

    The Pydantic validators ensure data integrity.
    """

    def test_create_from_typed_values(self):
        """Create with already-typed values."""
        txn = ParsedTransaction(
            date=datetime.date(2025, 3, 20),
            amount=Decimal("-742.18"),
            payee="MERCHANT NAME",
        )
        assert txn.date == datetime.date(2025, 3, 20)
        assert txn.amount == Decimal("-742.18")

    def test_amount_validator_converts_string(self):
        """The amount validator converts string to Decimal."""
        txn = ParsedTransaction(
            date=datetime.date(2025, 3, 20),
            amount="-500.00",  # String input
        )
        assert isinstance(txn.amount, Decimal)
        assert txn.amount == Decimal("-500.00")

    def test_amount_validator_preserves_decimal(self):
        """Decimal values pass through unchanged."""
        txn = ParsedTransaction(
            date=datetime.date(2025, 3, 20),
            amount=Decimal("123.45"),
        )
        assert txn.amount == Decimal("123.45")

    def test_requires_date(self):
        """Date is required - cannot create without it."""
        with pytest.raises(ValidationError):
            ParsedTransaction(amount="-100.00")

    def test_requires_amount(self):
        """Amount is required - cannot create without it."""
        with pytest.raises(ValidationError):
            ParsedTransaction(date=datetime.date(2025, 3, 20))

    def test_invalid_amount_string_raises_error(self):
        """Invalid amount strings should raise ValidationError."""
        with pytest.raises((ValidationError, Exception)):
            ParsedTransaction(
                date=datetime.date(2025, 3, 20),
                amount="not-a-number",
            )

    def test_memo_defaults_to_empty_string(self):
        """Memo defaults to empty string (not None) for cleaner output."""
        txn = ParsedTransaction(
            date=datetime.date(2025, 3, 20),
            amount="-100.00",
        )
        assert txn.memo == ""


# =============================================================================
# BeanTransaction Tests (Stage 3: Beancount-ready)
# =============================================================================


class TestBeanTransaction:
    """Tests for BeanTransaction - ready for Beancount directive creation.

    This is the final model before creating actual beancount.core.data objects.
    It includes all the enriched fields needed for a complete transaction.
    """

    def test_create_complete_transaction(self, bean_transaction):
        """A complete BeanTransaction has all fields for directive creation."""
        assert bean_transaction.date == datetime.date(2025, 3, 20)
        assert bean_transaction.amount == Decimal("-742.18")
        assert bean_transaction.currency == "NOK"
        assert bean_transaction.account == "Liabilities:CreditCard:Amex"
        assert bean_transaction.matched_account == "Expenses:Groceries"

    def test_default_flag_is_complete(self):
        """Default flag is '*' (complete/cleared transaction)."""
        txn = BeanTransaction(
            date=datetime.date(2025, 3, 20),
            amount=Decimal("-100.00"),
            currency="NOK",
        )
        assert txn.flag == "*"

    def test_empty_tags_and_links_by_default(self):
        """Tags and links default to empty sets."""
        txn = BeanTransaction(
            date=datetime.date(2025, 3, 20),
            amount=Decimal("-100.00"),
            currency="NOK",
        )
        assert txn.tags == set()
        assert txn.links == set()

    def test_metadata_as_dict(self, bean_transaction):
        """Metadata is a dict for arbitrary key-value pairs."""
        assert isinstance(bean_transaction.metadata, dict)
        assert bean_transaction.metadata["id"] == "AT250800024000010012345"
        assert bean_transaction.metadata["type"] == "DEBIT"

    def test_matched_account_is_optional(self):
        """matched_account is None when no categorization rule applies."""
        txn = BeanTransaction(
            date=datetime.date(2025, 3, 20),
            amount=Decimal("-100.00"),
            currency="NOK",
        )
        assert txn.matched_account is None


# =============================================================================
# QboFileData Tests (Complete file extraction)
# =============================================================================


class TestQboFileData:
    """Tests for QboFileData - container for all data from a QBO file.

    This model holds the complete result of parsing a QBO file:
    - All transactions
    - Balance and balance date
    - Account identification info
    """

    def test_create_complete_file_data(self, qbo_file_data):
        """Complete file data includes transactions and balance info."""
        assert len(qbo_file_data.transactions) == 2
        assert qbo_file_data.balance == "-35768.92"
        assert qbo_file_data.balance_date == datetime.date(2025, 3, 22)
        assert qbo_file_data.currency == "NOK"
        assert qbo_file_data.account_id == "XYZ|98765"
        assert qbo_file_data.organization == "AMEX"

    def test_empty_file_data(self):
        """Empty QboFileData is valid (for error cases)."""
        data = QboFileData()
        assert data.transactions == []
        assert data.balance is None
        assert data.currency is None

    def test_transactions_list_contains_raw_transactions(self, qbo_file_data):
        """Transactions list holds RawTransaction objects."""
        for txn in qbo_file_data.transactions:
            assert isinstance(txn, RawTransaction)

    def test_account_id_for_multi_card_support(self, qbo_file_data):
        """account_id enables matching specific Amex cards."""
        assert qbo_file_data.account_id == "XYZ|98765"
