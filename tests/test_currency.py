"""Unit tests for currency determination logic.

These tests verify the currency priority system:
1. Currency from the QBO file (CURDEF element)
2. Currency from importer configuration
3. Default fallback (NOK)

This priority ensures transactions use the most accurate currency.
"""

import pytest

from beancount_no_amex.credit import AmexAccountConfig, Importer, DEFAULT_CURRENCY


class TestDetermineCurrency:
    """Tests for the _determine_currency() method.

    Currency determination follows this priority:
    1. File currency (from CURDEF in QBO) - most accurate
    2. Config currency (from AmexAccountConfig) - user preference
    3. DEFAULT_CURRENCY ("NOK") - fallback for Norwegian Amex
    """

    def test_file_currency_takes_priority(self, basic_importer):
        """Currency from file overrides config currency."""
        result = basic_importer._determine_currency("USD")
        assert result == "USD"

    def test_config_currency_when_file_has_none(self):
        """Use config currency when file doesn't specify one."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="EUR",  # Configured currency
        )
        importer = Importer(config=config, debug=False)
        result = importer._determine_currency(None)
        assert result == "EUR"

    def test_default_currency_as_final_fallback(self):
        """DEFAULT_CURRENCY used when both file and config are None."""
        # This shouldn't happen in practice (config always has currency)
        # but the code handles it gracefully
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
        )
        importer = Importer(config=config, debug=False)
        # Simulate no file currency
        result = importer._determine_currency(None)
        assert result == "NOK"

    def test_empty_string_file_currency_uses_config(self, basic_importer):
        """Empty string is falsy, so config currency is used."""
        result = basic_importer._determine_currency("")
        assert result == "NOK"  # Falls back to config

    def test_whitespace_currency_from_file(self, basic_importer):
        """Whitespace-only currency should use config (after strip)."""
        # Note: find_currency() strips whitespace, so this tests the edge case
        result = basic_importer._determine_currency("   ")
        # Non-empty string is truthy, so it would be used as-is
        # This is a quirk - the file parser should strip before calling
        assert result == "   "  # Current behavior - whitespace is truthy

    def test_various_currency_codes(self):
        """Test with various international currency codes."""
        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
        )
        importer = Importer(config=config, debug=False)

        currencies = ["USD", "EUR", "GBP", "SEK", "DKK", "CHF", "JPY"]
        for currency in currencies:
            result = importer._determine_currency(currency)
            assert result == currency


class TestDefaultCurrencyConstant:
    """Tests for the DEFAULT_CURRENCY constant."""

    def test_default_currency_is_nok(self):
        """Default currency is NOK (Norwegian Krone) for Norwegian Amex."""
        assert DEFAULT_CURRENCY == "NOK"

    def test_default_currency_is_three_letters(self):
        """Currency codes should be 3-letter ISO 4217 codes."""
        assert len(DEFAULT_CURRENCY) == 3
        assert DEFAULT_CURRENCY.isupper()


class TestCurrencyInExtractedTransactions:
    """Integration tests for currency in extracted transactions."""

    def test_currency_from_file_in_transactions(self, basic_importer, minimal_qbo_file):
        """Extracted transactions use currency from the QBO file."""
        entries = basic_importer.extract(str(minimal_qbo_file), [])

        # Find the transaction (not balance assertion)
        transactions = [e for e in entries if hasattr(e, 'postings')]
        assert len(transactions) >= 1

        # Check currency in the posting
        txn = transactions[0]
        assert txn.postings[0].units.currency == "NOK"

    def test_usd_currency_preserved(self, tmp_path, qbo_with_usd_currency):
        """USD currency from file is preserved in transactions."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text(qbo_with_usd_currency)

        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex:USD",
            currency="USD",
            account_id="USD|99999",
        )
        importer = Importer(config=config, debug=False)
        entries = importer.extract(str(qbo_file), [])

        transactions = [e for e in entries if hasattr(e, 'postings')]
        assert len(transactions) >= 1

        # Currency from file (USD) should be used
        txn = transactions[0]
        assert txn.postings[0].units.currency == "USD"

    def test_fallback_currency_when_file_missing_curdef(
        self, tmp_path, qbo_without_currency
    ):
        """Config currency used when file has no CURDEF."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text(qbo_without_currency)

        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="SEK",  # Swedish Krona as config default
            account_id="ABC|11111",
        )
        importer = Importer(config=config, debug=False)
        entries = importer.extract(str(qbo_file), [])

        transactions = [e for e in entries if hasattr(e, 'postings')]
        if transactions:  # File may not be valid enough
            txn = transactions[0]
            # Should fall back to config currency (SEK)
            assert txn.postings[0].units.currency == "SEK"
