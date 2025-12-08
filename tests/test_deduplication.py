"""Tests for FITID-based transaction deduplication.

These tests verify that:
1. Transactions with FITIDs matching existing entries are skipped
2. New transactions (no matching FITID) are imported
3. The skip_deduplication config option bypasses deduplication
4. Transactions without FITIDs are always imported
"""

import datetime
from decimal import Decimal

import pytest
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D

from beancount_no_amex.credit import AmexAccountConfig, Importer


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config_with_deduplication() -> AmexAccountConfig:
    """Configuration with deduplication enabled (default)."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex",
        currency="NOK",
    )


@pytest.fixture
def config_skip_deduplication() -> AmexAccountConfig:
    """Configuration with deduplication disabled."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex",
        currency="NOK",
        skip_deduplication=True,
    )


@pytest.fixture
def importer_with_deduplication(config_with_deduplication) -> Importer:
    """Importer with deduplication enabled."""
    return Importer(config=config_with_deduplication, debug=False)


@pytest.fixture
def importer_skip_deduplication(config_skip_deduplication) -> Importer:
    """Importer with deduplication disabled."""
    return Importer(config=config_skip_deduplication, debug=False)


@pytest.fixture
def qbo_with_two_transactions(tmp_path):
    """QBO file with two transactions for testing deduplication."""
    content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <CCSTMTRS>
        <CURDEF>NOK</CURDEF>
        <CCACCTFROM><ACCTID>XYZ|98765</ACCTID></CCACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250320</DTPOSTED>
            <TRNAMT>-100.00</TRNAMT>
            <FITID>FITID001</FITID>
            <NAME>MERCHANT ONE</NAME>
          </STMTTRN>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250321</DTPOSTED>
            <TRNAMT>-200.00</TRNAMT>
            <FITID>FITID002</FITID>
            <NAME>MERCHANT TWO</NAME>
          </STMTTRN>
        </BANKTRANLIST>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
    qbo_file = tmp_path / "activity.qbo"
    qbo_file.write_text(content)
    return qbo_file


@pytest.fixture
def qbo_with_no_fitid(tmp_path):
    """QBO file with a transaction missing FITID."""
    content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <CCSTMTRS>
        <CURDEF>NOK</CURDEF>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250320</DTPOSTED>
            <TRNAMT>-50.00</TRNAMT>
            <!-- No FITID -->
            <NAME>NO FITID MERCHANT</NAME>
          </STMTTRN>
        </BANKTRANLIST>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
    qbo_file = tmp_path / "activity.qbo"
    qbo_file.write_text(content)
    return qbo_file


def create_existing_transaction(fitid: str, date: datetime.date, amount: Decimal) -> data.Transaction:
    """Helper to create a mock existing transaction with a FITID."""
    meta = {"filename": "existing.beancount", "lineno": 1, "id": fitid}
    posting = data.Posting(
        "Liabilities:CreditCard:Amex",
        Amount(amount, "NOK"),
        None, None, None, None
    )
    return data.Transaction(
        meta=meta,
        date=date,
        flag="*",
        payee="EXISTING MERCHANT",
        narration="EXISTING MERCHANT",
        tags=data.EMPTY_SET,
        links=data.EMPTY_SET,
        postings=[posting],
    )


# =============================================================================
# Tests for _extract_existing_fitids helper
# =============================================================================


class TestExtractExistingFitids:
    """Tests for the _extract_existing_fitids helper method."""

    def test_extracts_fitids_from_transactions(self, importer_with_deduplication):
        """Extracts FITIDs from transaction metadata."""
        existing = [
            create_existing_transaction("FITID001", datetime.date(2025, 3, 1), D("-100")),
            create_existing_transaction("FITID002", datetime.date(2025, 3, 2), D("-200")),
        ]

        fitids = importer_with_deduplication._extract_existing_fitids(existing)

        assert fitids == {"FITID001", "FITID002"}

    def test_ignores_non_transaction_directives(self, importer_with_deduplication):
        """Non-transaction directives (like Balance) are ignored."""
        balance = data.Balance(
            meta={"filename": "test.beancount", "lineno": 1},
            date=datetime.date(2025, 3, 1),
            account="Liabilities:CreditCard:Amex",
            amount=Amount(D("-100"), "NOK"),
            tolerance=None,
            diff_amount=None,
        )
        existing = [balance]

        fitids = importer_with_deduplication._extract_existing_fitids(existing)

        assert fitids == set()

    def test_ignores_transactions_without_id(self, importer_with_deduplication):
        """Transactions without 'id' metadata are ignored."""
        meta = {"filename": "test.beancount", "lineno": 1}  # No 'id' field
        posting = data.Posting(
            "Liabilities:CreditCard:Amex",
            Amount(D("-100"), "NOK"),
            None, None, None, None
        )
        txn = data.Transaction(
            meta=meta,
            date=datetime.date(2025, 3, 1),
            flag="*",
            payee="NO ID",
            narration="NO ID",
            tags=data.EMPTY_SET,
            links=data.EMPTY_SET,
            postings=[posting],
        )

        fitids = importer_with_deduplication._extract_existing_fitids([txn])

        assert fitids == set()

    def test_empty_existing_entries(self, importer_with_deduplication):
        """Empty existing entries returns empty set."""
        fitids = importer_with_deduplication._extract_existing_fitids([])

        assert fitids == set()


# =============================================================================
# Tests for deduplication in extract()
# =============================================================================


class TestDeduplication:
    """Tests for FITID-based deduplication during extraction."""

    def test_skips_duplicate_transactions(
        self, importer_with_deduplication, qbo_with_two_transactions
    ):
        """Transactions with matching FITIDs in existing entries are skipped."""
        existing = [
            create_existing_transaction("FITID001", datetime.date(2025, 3, 20), D("-100")),
        ]

        entries = importer_with_deduplication.extract(str(qbo_with_two_transactions), existing)
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # FITID001 should be skipped, only FITID002 should be imported
        assert len(transactions) == 1
        assert transactions[0].meta["id"] == "FITID002"

    def test_imports_new_transactions(
        self, importer_with_deduplication, qbo_with_two_transactions
    ):
        """Transactions without matching FITIDs are imported."""
        existing = [
            create_existing_transaction("DIFFERENT_FITID", datetime.date(2025, 3, 1), D("-50")),
        ]

        entries = importer_with_deduplication.extract(str(qbo_with_two_transactions), existing)
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Both transactions should be imported (no matching FITIDs)
        assert len(transactions) == 2

    def test_skips_all_duplicates(
        self, importer_with_deduplication, qbo_with_two_transactions
    ):
        """All duplicate transactions are skipped when all FITIDs match."""
        existing = [
            create_existing_transaction("FITID001", datetime.date(2025, 3, 20), D("-100")),
            create_existing_transaction("FITID002", datetime.date(2025, 3, 21), D("-200")),
        ]

        entries = importer_with_deduplication.extract(str(qbo_with_two_transactions), existing)
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Both transactions should be skipped
        assert len(transactions) == 0

    def test_empty_existing_entries_imports_all(
        self, importer_with_deduplication, qbo_with_two_transactions
    ):
        """All transactions are imported when existing entries is empty."""
        entries = importer_with_deduplication.extract(str(qbo_with_two_transactions), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        assert len(transactions) == 2

    def test_transactions_without_fitid_always_imported(
        self, importer_with_deduplication, qbo_with_no_fitid
    ):
        """Transactions without FITID are always imported (cannot deduplicate)."""
        existing = [
            create_existing_transaction("SOME_FITID", datetime.date(2025, 3, 1), D("-50")),
        ]

        entries = importer_with_deduplication.extract(str(qbo_with_no_fitid), existing)
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Transaction without FITID should be imported
        assert len(transactions) == 1
        assert "id" not in transactions[0].meta


# =============================================================================
# Tests for skip_deduplication config option
# =============================================================================


class TestSkipDeduplication:
    """Tests for the skip_deduplication configuration option."""

    def test_skip_deduplication_imports_duplicates(
        self, importer_skip_deduplication, qbo_with_two_transactions
    ):
        """With skip_deduplication=True, duplicate FITIDs are imported anyway."""
        existing = [
            create_existing_transaction("FITID001", datetime.date(2025, 3, 20), D("-100")),
            create_existing_transaction("FITID002", datetime.date(2025, 3, 21), D("-200")),
        ]

        entries = importer_skip_deduplication.extract(str(qbo_with_two_transactions), existing)
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Both transactions should be imported despite matching FITIDs
        assert len(transactions) == 2

    def test_skip_deduplication_default_is_false(self, config_with_deduplication):
        """Default value for skip_deduplication is False."""
        assert config_with_deduplication.skip_deduplication is False

    def test_skip_deduplication_can_be_enabled(self, config_skip_deduplication):
        """skip_deduplication can be set to True."""
        assert config_skip_deduplication.skip_deduplication is True


# =============================================================================
# Integration tests with real sample file
# =============================================================================


class TestDeduplicationWithRealFile:
    """Integration tests using the real sample QBO file."""

    def test_deduplication_with_sample_file(self, importer_with_deduplication, sample_qbo_path):
        """Test deduplication with the real sample activity.qbo file."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        # First import - should get all transactions
        first_import = importer_with_deduplication.extract(str(sample_qbo_path), [])
        first_transactions = [e for e in first_import if isinstance(e, data.Transaction)]

        # Second import with first import as existing entries - should get no new transactions
        second_import = importer_with_deduplication.extract(str(sample_qbo_path), first_import)
        second_transactions = [e for e in second_import if isinstance(e, data.Transaction)]

        # All transactions from first import should be skipped in second import
        assert len(first_transactions) == 9  # Sample file has 9 transactions
        assert len(second_transactions) == 0

    def test_partial_deduplication_with_sample_file(
        self, importer_with_deduplication, sample_qbo_path
    ):
        """Test that only matching FITIDs are deduplicated."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        # First import
        first_import = importer_with_deduplication.extract(str(sample_qbo_path), [])
        first_transactions = [e for e in first_import if isinstance(e, data.Transaction)]

        # Keep only first 5 transactions as "existing"
        partial_existing = first_transactions[:5]

        # Second import should only import the remaining 4 transactions
        second_import = importer_with_deduplication.extract(str(sample_qbo_path), partial_existing)
        second_transactions = [e for e in second_import if isinstance(e, data.Transaction)]

        assert len(second_transactions) == 4
