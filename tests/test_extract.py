"""Integration tests for the full extraction pipeline (extract method).

These tests verify the complete data flow:
    QBO File → parse → transform → categorize → Beancount Directives

This is where all the pieces come together.
"""

import datetime
from decimal import Decimal

import pytest
from beancount.core import data
from beancount.core.number import D

from beancount_no_amex.credit import AmexAccountConfig, Importer


class TestExtractBasics:
    """Basic extraction tests - the happy path."""

    def test_extract_returns_list_of_directives(self, basic_importer, minimal_qbo_file):
        """extract() returns a list of Beancount directives."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_extract_creates_transaction_directive(
        self, basic_importer, minimal_qbo_file
    ):
        """Each transaction in the QBO becomes a Transaction directive."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        assert len(transactions) >= 1

    def test_extract_creates_balance_directive(self, importer_with_balance_assertions, minimal_qbo_file):
        """Balance assertion is created from LEDGERBAL when enabled."""
        entries = importer_with_balance_assertions.extract(str(minimal_qbo_file), [])

        balances = [e for e in entries if isinstance(e, data.Balance)]
        assert len(balances) == 1

    def test_extract_no_balance_by_default(self, basic_importer, minimal_qbo_file):
        """Balance assertions are not created by default."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        balances = [e for e in entries if isinstance(e, data.Balance)]
        assert len(balances) == 0

    def test_transaction_has_correct_date(self, basic_importer, minimal_qbo_file):
        """Transaction date is correctly parsed from DTPOSTED."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        assert transactions[0].date == datetime.date(2025, 3, 20)

    def test_transaction_has_correct_amount(self, basic_importer, minimal_qbo_file):
        """Transaction amount is correctly parsed from TRNAMT."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        txn = transactions[0]
        assert txn.postings[0].units.number == D("-100.00")

    def test_transaction_has_correct_account(self, basic_importer, minimal_qbo_file):
        """Transaction uses the configured account name."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        txn = transactions[0]
        assert txn.postings[0].account == "Liabilities:CreditCard:Amex"


class TestExtractWithCategorization:
    """Tests for extraction with categorization mappings."""

    def test_matching_transactions_get_categorized(
        self, importer_with_mappings, sample_qbo_path
    ):
        """Transactions matching patterns get expense accounts."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = importer_with_mappings.extract(str(sample_qbo_path), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Find the VINMONOPOLET transaction
        vinmonopolet_txn = next(
            (t for t in transactions if "VINMONOPOLET" in (t.narration or "")), None
        )

        assert vinmonopolet_txn is not None
        # Should have two postings (credit card + expense)
        assert len(vinmonopolet_txn.postings) == 2
        assert vinmonopolet_txn.postings[1].account == "Expenses:Groceries"

    def test_unmatched_transactions_have_one_posting(
        self, importer_with_mappings, sample_qbo_path
    ):
        """Transactions not matching patterns have only the primary posting."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = importer_with_mappings.extract(str(sample_qbo_path), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Find a transaction that doesn't match any pattern (e.g., DISNEY)
        disney_txn = next(
            (t for t in transactions if "DISNEY" in (t.narration or "")), None
        )

        if disney_txn:
            # Should have only one posting (no categorization rule for DISNEY)
            assert len(disney_txn.postings) == 1


class TestExtractMetadata:
    """Tests for transaction metadata."""

    def test_transaction_has_id_metadata(self, basic_importer, minimal_qbo_file):
        """Transaction includes FITID as 'id' metadata."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        txn = transactions[0]
        assert "id" in txn.meta
        assert txn.meta["id"] == "TEST001"

    def test_transaction_has_type_metadata(self, basic_importer, minimal_qbo_file):
        """Transaction includes TRNTYPE as 'type' metadata."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        txn = transactions[0]
        assert "type" in txn.meta
        assert txn.meta["type"] == "DEBIT"

    def test_transaction_has_file_location_metadata(
        self, basic_importer, minimal_qbo_file
    ):
        """Transaction includes source file location in metadata."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        txn = transactions[0]
        assert "filename" in txn.meta
        assert "activity.qbo" in txn.meta["filename"]


class TestExtractBalanceAssertion:
    """Tests for balance assertion generation (requires generate_balance_assertions=True)."""

    def test_balance_date_is_day_after_statement(
        self, importer_with_balance_assertions, minimal_qbo_file
    ):
        """Balance assertion is for the day after the statement date."""
        entries = importer_with_balance_assertions.extract(str(minimal_qbo_file), [])

        balances = [e for e in entries if isinstance(e, data.Balance)]
        assert len(balances) == 1

        # Statement date is 2025-03-20, assertion should be 2025-03-21
        assert balances[0].date == datetime.date(2025, 3, 21)

    def test_balance_amount_from_ledgerbal(self, importer_with_balance_assertions, minimal_qbo_file):
        """Balance amount comes from LEDGERBAL/BALAMT."""
        entries = importer_with_balance_assertions.extract(str(minimal_qbo_file), [])

        balances = [e for e in entries if isinstance(e, data.Balance)]
        assert balances[0].amount.number == D("-100.00")

    def test_balance_uses_correct_account(self, importer_with_balance_assertions, minimal_qbo_file):
        """Balance assertion uses the configured account."""
        entries = importer_with_balance_assertions.extract(str(minimal_qbo_file), [])

        balances = [e for e in entries if isinstance(e, data.Balance)]
        assert balances[0].account == "Liabilities:CreditCard:Amex"


class TestExtractFromRealFile:
    """Tests using the real sample activity.qbo file."""

    def test_extract_all_transactions(self, basic_importer, sample_qbo_path):
        """Extract all 9 transactions from the sample file."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = basic_importer.extract(str(sample_qbo_path), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # The sample file has 9 transactions
        assert len(transactions) == 9

    def test_debit_transactions_are_negative(self, basic_importer, sample_qbo_path):
        """Debit transactions have negative amounts."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = basic_importer.extract(str(sample_qbo_path), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        debits = [t for t in transactions if t.meta.get("type") == "DEBIT"]
        for txn in debits:
            assert txn.postings[0].units.number < 0

    def test_credit_transactions_are_positive(self, basic_importer, sample_qbo_path):
        """Credit transactions (refunds/payments) have positive amounts."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = basic_importer.extract(str(sample_qbo_path), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        credits = [t for t in transactions if t.meta.get("type") == "CREDIT"]
        for txn in credits:
            assert txn.postings[0].units.number > 0

    def test_balance_assertion_matches_file(self, importer_with_balance_assertions, sample_qbo_path):
        """Balance assertion matches the LEDGERBAL from the file."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        entries = importer_with_balance_assertions.extract(str(sample_qbo_path), [])
        balances = [e for e in entries if isinstance(e, data.Balance)]

        assert len(balances) == 1
        assert balances[0].amount.number == D("-35768.92")
        # Balance date in file is 2025-03-22, assertion is day after
        assert balances[0].date == datetime.date(2025, 3, 23)


class TestExtractEdgeCases:
    """Edge cases for extraction."""

    def test_empty_file_returns_empty_list(self, basic_importer, tmp_path):
        """Empty/invalid QBO file returns empty list."""
        empty_file = tmp_path / "activity.qbo"
        empty_file.write_text("")

        entries = basic_importer.extract(str(empty_file), [])
        assert entries == []

    def test_file_without_transactions(self, importer_with_balance_assertions, tmp_path):
        """QBO file with no transactions returns only balance (when enabled)."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CURDEF>NOK</CURDEF>
      <BANKTRANLIST></BANKTRANLIST>
      <LEDGERBAL>
        <BALAMT>0.00</BALAMT>
        <DTASOF>20250320</DTASOF>
      </LEDGERBAL>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')

        entries = importer_with_balance_assertions.extract(str(qbo_file), [])

        # Should have only the balance assertion
        transactions = [e for e in entries if isinstance(e, data.Transaction)]
        balances = [e for e in entries if isinstance(e, data.Balance)]

        assert len(transactions) == 0
        assert len(balances) == 1

    def test_transaction_with_missing_date_is_skipped(self, basic_importer, tmp_path):
        """Transactions without dates are skipped."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CURDEF>NOK</CURDEF>
      <BANKTRANLIST>
        <STMTTRN>
          <TRNTYPE>DEBIT</TRNTYPE>
          <!-- No DTPOSTED -->
          <TRNAMT>-50.00</TRNAMT>
          <FITID>NODATE001</FITID>
          <NAME>NO DATE MERCHANT</NAME>
        </STMTTRN>
        <STMTTRN>
          <TRNTYPE>DEBIT</TRNTYPE>
          <DTPOSTED>20250320</DTPOSTED>
          <TRNAMT>-100.00</TRNAMT>
          <FITID>HASDATE001</FITID>
          <NAME>HAS DATE MERCHANT</NAME>
        </STMTTRN>
      </BANKTRANLIST>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')

        entries = basic_importer.extract(str(qbo_file), [])
        transactions = [e for e in entries if isinstance(e, data.Transaction)]

        # Only the transaction with a date should be extracted
        assert len(transactions) == 1
        assert transactions[0].meta["id"] == "HASDATE001"


class TestDateMethod:
    """Tests for the date() method."""

    def test_returns_latest_transaction_date(self, basic_importer, sample_qbo_path):
        """date() returns the latest transaction date from the file."""
        if not sample_qbo_path.exists():
            pytest.skip("Sample QBO file not available")

        result = basic_importer.date(str(sample_qbo_path))
        # The sample file has transactions dated 2025-03-19 and 2025-03-20
        assert result == datetime.date(2025, 3, 20)

    def test_returns_today_for_empty_file(self, basic_importer, tmp_path):
        """date() returns today's date for files with no valid transactions."""
        empty_file = tmp_path / "activity.qbo"
        empty_file.write_text("<OFX></OFX>")

        result = basic_importer.date(str(empty_file))
        assert result == datetime.date.today()
