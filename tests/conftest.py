"""Shared pytest fixtures for beancount-no-amex tests.

This module provides reusable test fixtures that demonstrate how each
component of the pipeline works. Reading these fixtures helps understand
the data flow through the importer.
"""

import datetime
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from beancount_no_amex.credit import AmexAccountConfig, Importer
from beancount_classifier import TransactionPattern, amount
from beancount_no_amex.models import (
    BeanTransaction,
    ParsedTransaction,
    QboFileData,
    RawTransaction,
)


# =============================================================================
# Path Fixtures
# =============================================================================


@pytest.fixture
def test_data_dir() -> Path:
    """Path to the test_data directory containing sample QBO files."""
    return Path(__file__).parent.parent / "test_data"


@pytest.fixture
def sample_qbo_path(test_data_dir) -> Path:
    """Path to the sample activity.qbo file."""
    return test_data_dir / "activity.qbo"


# =============================================================================
# Raw Data Fixtures (Stage 1: Direct from XML)
# =============================================================================


@pytest.fixture
def raw_transaction_debit() -> RawTransaction:
    """A typical debit transaction as extracted from QBO XML.

    All fields are strings - this is the raw state before parsing.
    """
    return RawTransaction(
        date="20250320000000.000[-7:MST]",
        amount="-742.18",
        payee="VINMONOPOLET GRUNERLOKKA OSLO",
        memo="LINA HANSEN-81023",
        id="AT250800024000010012345",
        type="DEBIT",
    )


@pytest.fixture
def raw_transaction_credit() -> RawTransaction:
    """A credit (refund/payment) transaction from QBO XML."""
    return RawTransaction(
        date="20250319000000.000[-7:MST]",
        amount="1200.00",
        payee="REFUND: SCANDIC HOTELS OSLO",
        memo="LINA HANSEN-81023",
        id="AT250790024000010005432",
        type="CREDIT",
    )


@pytest.fixture
def raw_transaction_minimal() -> RawTransaction:
    """Minimal valid transaction - only required fields."""
    return RawTransaction(
        date="20250320",
        amount="-100.00",
    )


@pytest.fixture
def raw_transaction_missing_date() -> RawTransaction:
    """Transaction with missing date - should be skipped during processing."""
    return RawTransaction(
        date=None,
        amount="-50.00",
        payee="SOME MERCHANT",
    )


# =============================================================================
# Parsed Data Fixtures (Stage 2: Typed Python objects)
# =============================================================================


@pytest.fixture
def parsed_transaction() -> ParsedTransaction:
    """A parsed transaction with proper Python types.

    This is the intermediate stage after parsing raw strings.
    """
    return ParsedTransaction(
        date=datetime.date(2025, 3, 20),
        amount=Decimal("-742.18"),
        payee="VINMONOPOLET GRUNERLOKKA OSLO",
        memo="LINA HANSEN-81023",
        id="AT250800024000010012345",
        type="DEBIT",
    )


# =============================================================================
# Bean Transaction Fixtures (Stage 3: Ready for Beancount)
# =============================================================================


@pytest.fixture
def bean_transaction() -> BeanTransaction:
    """A fully-formed transaction ready for Beancount directive creation."""
    return BeanTransaction(
        date=datetime.date(2025, 3, 20),
        amount=Decimal("-742.18"),
        currency="NOK",
        payee="VINMONOPOLET GRUNERLOKKA OSLO",
        narration="VINMONOPOLET GRUNERLOKKA OSLO",
        account="Liabilities:CreditCard:Amex",
        metadata={"id": "AT250800024000010012345", "type": "DEBIT"},
        matched_account="Expenses:Groceries",
    )


# =============================================================================
# QBO File Data Fixtures (Complete file extraction)
# =============================================================================


@pytest.fixture
def qbo_file_data(raw_transaction_debit, raw_transaction_credit) -> QboFileData:
    """Complete data extracted from a QBO file."""
    return QboFileData(
        transactions=[raw_transaction_debit, raw_transaction_credit],
        balance="-35768.92",
        balance_date=datetime.date(2025, 3, 22),
        currency="NOK",
        account_id="XYZ|98765",
        organization="AMEX",
    )


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def basic_config() -> AmexAccountConfig:
    """Basic importer configuration without account_id filtering."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex",
        currency="NOK",
    )


@pytest.fixture
def config_with_balance_assertions() -> AmexAccountConfig:
    """Configuration with balance assertions enabled."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex",
        currency="NOK",
        generate_balance_assertions=True,
    )


@pytest.fixture
def config_with_mappings() -> AmexAccountConfig:
    """Configuration with transaction patterns for categorization."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex",
        currency="NOK",
        transaction_patterns=[
            TransactionPattern(narration="VINMONOPOLET", account="Expenses:Groceries"),
            TransactionPattern(narration="SPOTIFY", account="Expenses:Entertainment:Music"),
            TransactionPattern(narration="NETFLIX", account="Expenses:Entertainment:Streaming"),
            TransactionPattern(narration="REMA", account="Expenses:Groceries"),
            TransactionPattern(narration="KIWI", account="Expenses:Groceries"),
        ],
    )


@pytest.fixture
def config_with_account_id() -> AmexAccountConfig:
    """Configuration for a specific account (multi-account support)."""
    return AmexAccountConfig(
        account_name="Liabilities:CreditCard:Amex:Personal",
        currency="NOK",
        account_id="XYZ|98765",
        transaction_patterns=[
            TransactionPattern(narration="VINMONOPOLET", account="Expenses:Groceries"),
        ],
    )


@pytest.fixture
def config_with_patterns() -> AmexAccountConfig:
    """Configuration with advanced patterns: regex, case-insensitive, amounts."""
    return AmexAccountConfig(
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


# =============================================================================
# Importer Fixtures
# =============================================================================


@pytest.fixture
def basic_importer(basic_config) -> Importer:
    """An importer with basic configuration."""
    return Importer(config=basic_config, debug=False)


@pytest.fixture
def importer_with_balance_assertions(config_with_balance_assertions) -> Importer:
    """An importer configured to generate balance assertions."""
    return Importer(config=config_with_balance_assertions, debug=False)


@pytest.fixture
def importer_with_mappings(config_with_mappings) -> Importer:
    """An importer configured with categorization mappings."""
    return Importer(config=config_with_mappings, debug=False)


@pytest.fixture
def importer_with_account_id(config_with_account_id) -> Importer:
    """An importer configured for a specific account ID."""
    return Importer(config=config_with_account_id, debug=False)


@pytest.fixture
def importer_with_patterns(config_with_patterns) -> Importer:
    """An importer configured with advanced transaction patterns."""
    return Importer(config=config_with_patterns, debug=False)


# =============================================================================
# QBO File Content Fixtures (for creating temp files)
# =============================================================================


@pytest.fixture
def minimal_qbo_content() -> str:
    """Minimal valid QBO file content for testing."""
    return '''<?xml version="1.0" standalone="no"?>
<?OFX OFXHEADER="200" VERSION="202" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <DTSERVER>20250320000000</DTSERVER>
      <LANGUAGE>ENG</LANGUAGE>
      <FI><ORG>AMEX</ORG></FI>
    </SONRS>
  </SIGNONMSGSRSV1>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <TRNUID>0</TRNUID>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <CCSTMTRS>
        <CURDEF>NOK</CURDEF>
        <CCACCTFROM><ACCTID>XYZ|98765</ACCTID></CCACCTFROM>
        <BANKTRANLIST>
          <DTSTART>20250319000000</DTSTART>
          <DTEND>20250320000000</DTEND>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250320000000</DTPOSTED>
            <TRNAMT>-100.00</TRNAMT>
            <FITID>TEST001</FITID>
            <NAME>TEST MERCHANT</NAME>
          </STMTTRN>
        </BANKTRANLIST>
        <LEDGERBAL>
          <BALAMT>-100.00</BALAMT>
          <DTASOF>20250320000000</DTASOF>
        </LEDGERBAL>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''


@pytest.fixture
def minimal_qbo_file(minimal_qbo_content, tmp_path) -> Path:
    """Create a temporary minimal QBO file for testing."""
    qbo_file = tmp_path / "activity.qbo"
    qbo_file.write_text(minimal_qbo_content)
    return qbo_file


@pytest.fixture
def qbo_without_currency() -> str:
    """QBO content without CURDEF tag - tests currency fallback."""
    return '''<?xml version="1.0"?>
<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <DTSERVER>20250320</DTSERVER>
      <LANGUAGE>ENG</LANGUAGE>
      <FI><ORG>AMEX</ORG></FI>
    </SONRS>
  </SIGNONMSGSRSV1>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <TRNUID>0</TRNUID>
      <CCSTMTRS>
        <CCACCTFROM><ACCTID>ABC|11111</ACCTID></CCACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250320</DTPOSTED>
            <TRNAMT>-50.00</TRNAMT>
            <FITID>NOCUR001</FITID>
            <NAME>NO CURRENCY MERCHANT</NAME>
          </STMTTRN>
        </BANKTRANLIST>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''


@pytest.fixture
def qbo_with_usd_currency() -> str:
    """QBO content with USD currency - tests non-NOK handling."""
    return '''<?xml version="1.0"?>
<OFX>
  <SIGNONMSGSRSV1>
    <SONRS>
      <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
      <DTSERVER>20250320</DTSERVER>
      <LANGUAGE>ENG</LANGUAGE>
      <FI><ORG>AMEX</ORG></FI>
    </SONRS>
  </SIGNONMSGSRSV1>
  <CREDITCARDMSGSRSV1>
    <CCSTMTTRNRS>
      <TRNUID>0</TRNUID>
      <CCSTMTRS>
        <CURDEF>USD</CURDEF>
        <CCACCTFROM><ACCTID>USD|99999</ACCTID></CCACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20250320</DTPOSTED>
            <TRNAMT>-25.99</TRNAMT>
            <FITID>USD001</FITID>
            <NAME>US MERCHANT</NAME>
          </STMTTRN>
        </BANKTRANLIST>
      </CCSTMTRS>
    </CCSTMTTRNRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
