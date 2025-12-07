"""Unit tests for parsing functions (credit.py).

These tests cover the low-level parsing utilities that extract and
transform data from QBO/OFX files:

- parse_ofx_time(): Parse OFX timestamp formats
- find_account_id(): Quick account ID extraction
- find_currency(): Currency code extraction
"""

import datetime
from pathlib import Path

import pytest

from beancount_no_amex.credit import (
    find_account_id,
    find_currency,
    parse_ofx_time,
)


# =============================================================================
# parse_ofx_time() Tests
# =============================================================================


class TestParseOfxTime:
    """Tests for OFX timestamp parsing.

    OFX/QBO files use two timestamp formats:
    - Short: YYYYMMDD (8 characters)
    - Long:  YYYYMMDDHHMMSS (14+ characters, may include timezone)

    The function extracts just the date/time portion.
    """

    def test_parse_short_date_format(self):
        """Parse YYYYMMDD format (8 characters)."""
        result = parse_ofx_time("20250320")
        assert result == datetime.datetime(2025, 3, 20)

    def test_parse_long_datetime_format(self):
        """Parse YYYYMMDDHHMMSS format (14 characters)."""
        result = parse_ofx_time("20250320143052")
        assert result == datetime.datetime(2025, 3, 20, 14, 30, 52)

    def test_parse_datetime_with_timezone_suffix(self):
        """Timezone suffixes are stripped (we only care about the date)."""
        # This is the format seen in real Amex QBO files
        result = parse_ofx_time("20250320000000.000[-7:MST]")
        assert result.date() == datetime.date(2025, 3, 20)

    def test_parse_datetime_with_fractional_seconds(self):
        """Fractional seconds are handled (stripped with timezone)."""
        result = parse_ofx_time("20250320143052.123")
        assert result == datetime.datetime(2025, 3, 20, 14, 30, 52)

    def test_extract_date_from_result(self):
        """Common pattern: extract just the date from the result."""
        result = parse_ofx_time("20250320000000.000[-7:MST]")
        date_only = result.date()
        assert date_only == datetime.date(2025, 3, 20)

    def test_various_real_world_formats(self):
        """Test formats seen in actual QBO files."""
        test_cases = [
            ("20250319000000.000[-7:MST]", datetime.date(2025, 3, 19)),
            ("20250322000000.000[-7:MST]", datetime.date(2025, 3, 22)),
            ("20250101", datetime.date(2025, 1, 1)),
            ("20241231235959", datetime.date(2024, 12, 31)),
        ]
        for date_str, expected_date in test_cases:
            result = parse_ofx_time(date_str)
            assert result.date() == expected_date, f"Failed for {date_str}"

    def test_invalid_format_raises_error(self):
        """Invalid date strings raise ValueError."""
        with pytest.raises(ValueError):
            parse_ofx_time("not-a-date")

    def test_empty_string_raises_error(self):
        """Empty string raises an error."""
        with pytest.raises((ValueError, IndexError)):
            parse_ofx_time("")


# =============================================================================
# find_account_id() Tests
# =============================================================================


class TestFindAccountId:
    """Tests for quick account ID extraction.

    This function does a lightweight parse to find the ACCTID element,
    used during file identification to match specific accounts.
    """

    def test_find_account_id_in_real_file(self, sample_qbo_path):
        """Extract account ID from the sample QBO file."""
        if sample_qbo_path.exists():
            result = find_account_id(str(sample_qbo_path))
            assert result == "XYZ|98765"

    def test_find_account_id_in_minimal_file(self, minimal_qbo_file):
        """Extract account ID from minimal QBO content."""
        result = find_account_id(str(minimal_qbo_file))
        assert result == "XYZ|98765"

    def test_returns_none_for_missing_acctid(self, tmp_path):
        """Return None if no ACCTID element exists."""
        qbo_file = tmp_path / "no_acct.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <BANKTRANLIST></BANKTRANLIST>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')
        result = find_account_id(str(qbo_file))
        assert result is None

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Return None for files that don't exist."""
        result = find_account_id(str(tmp_path / "nonexistent.qbo"))
        assert result is None

    def test_returns_none_for_invalid_xml(self, tmp_path):
        """Return None for malformed XML (graceful error handling)."""
        bad_file = tmp_path / "bad.qbo"
        bad_file.write_text("this is not xml at all")
        result = find_account_id(str(bad_file))
        assert result is None

    def test_finds_ccacctfrom_acctid(self, tmp_path):
        """Find ACCTID inside CCACCTFROM (credit card accounts)."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CCACCTFROM><ACCTID>CC|12345</ACCTID></CCACCTFROM>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')
        result = find_account_id(str(qbo_file))
        assert result == "CC|12345"

    def test_finds_bankacctfrom_acctid(self, tmp_path):
        """Find ACCTID inside BANKACCTFROM (bank accounts)."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <BANKMSGSRSV1>
    <STMTRS>
      <BANKACCTFROM><ACCTID>BANK|67890</ACCTID></BANKACCTFROM>
    </STMTRS>
  </BANKMSGSRSV1>
</OFX>''')
        result = find_account_id(str(qbo_file))
        assert result == "BANK|67890"


# =============================================================================
# find_currency() Tests
# =============================================================================


class TestFindCurrency:
    """Tests for currency extraction from QBO files.

    Currency is specified in the CURDEF element within statement sections.
    """

    def test_find_currency_in_ccstmtrs(self, tmp_path):
        """Find currency in credit card statement response."""
        from lxml import etree

        qbo_content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CURDEF>NOK</CURDEF>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
        tree = etree.fromstring(qbo_content.encode())
        result = find_currency(tree)
        assert result == "NOK"

    def test_find_currency_usd(self, tmp_path):
        """Find non-NOK currency (USD)."""
        from lxml import etree

        qbo_content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CURDEF>USD</CURDEF>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
        tree = etree.fromstring(qbo_content.encode())
        result = find_currency(tree)
        assert result == "USD"

    def test_returns_none_when_no_curdef(self):
        """Return None when no CURDEF element exists."""
        from lxml import etree

        qbo_content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CCACCTFROM><ACCTID>ABC</ACCTID></CCACCTFROM>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
        tree = etree.fromstring(qbo_content.encode())
        result = find_currency(tree)
        assert result is None

    def test_strips_whitespace_from_currency(self):
        """Currency codes are stripped of whitespace."""
        from lxml import etree

        qbo_content = '''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CURDEF>  EUR  </CURDEF>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>'''
        tree = etree.fromstring(qbo_content.encode())
        result = find_currency(tree)
        assert result == "EUR"

    def test_finds_curdef_in_stmtrs(self):
        """Find CURDEF in bank statement response (STMTRS)."""
        from lxml import etree

        qbo_content = '''<?xml version="1.0"?>
<OFX>
  <BANKMSGSRSV1>
    <STMTRS>
      <CURDEF>SEK</CURDEF>
    </STMTRS>
  </BANKMSGSRSV1>
</OFX>'''
        tree = etree.fromstring(qbo_content.encode())
        result = find_currency(tree)
        assert result == "SEK"
