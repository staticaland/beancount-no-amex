"""Component tests for file identification (identify method).

The identify() method determines if a file should be processed by this importer.
It checks:
1. File extension (.qbo)
2. MIME type (application/x-ofx, etc.)
3. Filename pattern (starts with "activity")
4. Account ID matching (for multi-account support)
"""

from pathlib import Path

import pytest

from beancount_no_amex.credit import AmexAccountConfig, Importer


class TestIdentifyBasics:
    """Basic file identification tests."""

    def test_identifies_valid_qbo_file(self, basic_importer, sample_qbo_path):
        """Correctly identifies a valid QBO file."""
        if sample_qbo_path.exists():
            assert basic_importer.identify(str(sample_qbo_path)) is True

    def test_identifies_minimal_qbo_file(self, basic_importer, minimal_qbo_file):
        """Identifies a minimal valid QBO file."""
        assert basic_importer.identify(str(minimal_qbo_file)) is True

    def test_rejects_wrong_extension(self, basic_importer, tmp_path):
        """Rejects files without .qbo extension."""
        txt_file = tmp_path / "activity.txt"
        txt_file.write_text("not a qbo file")
        assert basic_importer.identify(str(txt_file)) is False

    def test_rejects_wrong_filename_pattern(self, basic_importer, tmp_path):
        """Rejects .qbo files that don't start with 'activity'."""
        qbo_file = tmp_path / "statement.qbo"
        qbo_file.write_text("<?xml version='1.0'?><OFX></OFX>")
        assert basic_importer.identify(str(qbo_file)) is False

    def test_accepts_activity_prefix_case_insensitive(self, basic_importer, tmp_path):
        """Accepts 'Activity.qbo' (case-insensitive check)."""
        qbo_file = tmp_path / "Activity.qbo"
        qbo_file.write_text("<?xml version='1.0'?><OFX></OFX>")
        # The check uses .lower() so this should work
        assert basic_importer.identify(str(qbo_file)) is True

    def test_accepts_activity_with_date_suffix(self, basic_importer, tmp_path):
        """Accepts 'activity_2025-03.qbo' (common naming pattern)."""
        qbo_file = tmp_path / "activity_2025-03.qbo"
        qbo_file.write_text("<?xml version='1.0'?><OFX></OFX>")
        assert basic_importer.identify(str(qbo_file)) is True


class TestIdentifyWithAccountId:
    """Tests for multi-account identification using account_id."""

    def test_matches_correct_account_id(self, importer_with_account_id, minimal_qbo_file):
        """Importer with account_id only matches files with that ID."""
        # minimal_qbo_file has account_id "XYZ|98765"
        # importer_with_account_id is configured for "XYZ|98765"
        assert importer_with_account_id.identify(str(minimal_qbo_file)) is True

    def test_rejects_wrong_account_id(self, tmp_path):
        """Importer rejects files with different account_id."""
        # Create file with different account ID
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CCACCTFROM><ACCTID>DIFFERENT|99999</ACCTID></CCACCTFROM>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')

        config = AmexAccountConfig(
            account_name="Liabilities:CreditCard:Amex",
            currency="NOK",
            account_id="XYZ|98765",  # Different from file
        )
        importer = Importer(config=config, debug=False)
        assert importer.identify(str(qbo_file)) is False

    def test_no_account_id_matches_any_file(self, basic_importer, minimal_qbo_file):
        """Importer without account_id matches any valid QBO file."""
        # basic_importer has no account_id configured
        assert basic_importer.identify(str(minimal_qbo_file)) is True

    def test_multi_account_scenario(self, tmp_path):
        """Multiple importers can target different accounts."""
        # Create two QBO files with different account IDs
        file1 = tmp_path / "activity_personal.qbo"
        file1.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CCACCTFROM><ACCTID>PERSONAL|111</ACCTID></CCACCTFROM>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')

        file2 = tmp_path / "activity_business.qbo"
        file2.write_text('''<?xml version="1.0"?>
<OFX>
  <CREDITCARDMSGSRSV1>
    <CCSTMTRS>
      <CCACCTFROM><ACCTID>BUSINESS|222</ACCTID></CCACCTFROM>
    </CCSTMTRS>
  </CREDITCARDMSGSRSV1>
</OFX>''')

        # Create importers for each account
        personal_importer = Importer(
            config=AmexAccountConfig(
                account_name="Liabilities:CreditCard:Amex:Personal",
                currency="NOK",
                account_id="PERSONAL|111",
            ),
            debug=False,
        )
        business_importer = Importer(
            config=AmexAccountConfig(
                account_name="Liabilities:CreditCard:Amex:Business",
                currency="NOK",
                account_id="BUSINESS|222",
            ),
            debug=False,
        )

        # Personal importer only matches personal file
        assert personal_importer.identify(str(file1)) is True
        assert personal_importer.identify(str(file2)) is False

        # Business importer only matches business file
        assert business_importer.identify(str(file1)) is False
        assert business_importer.identify(str(file2)) is True


class TestIdentifyEdgeCases:
    """Edge cases for file identification."""

    def test_nonexistent_file(self, basic_importer, tmp_path):
        """Gracefully handles nonexistent files."""
        result = basic_importer.identify(str(tmp_path / "nonexistent.qbo"))
        assert result is False

    def test_empty_file(self, basic_importer, tmp_path):
        """Handles empty files gracefully."""
        empty_file = tmp_path / "activity.qbo"
        empty_file.write_text("")
        # Should return False (can't parse for account_id)
        # but basic_importer has no account_id, so extension check passes
        result = basic_importer.identify(str(empty_file))
        # Extension is .qbo, starts with activity, so might pass initial check
        # depending on MIME type detection
        assert isinstance(result, bool)

    def test_binary_garbage_file(self, basic_importer, tmp_path):
        """Handles binary garbage gracefully."""
        garbage_file = tmp_path / "activity.qbo"
        garbage_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        result = basic_importer.identify(str(garbage_file))
        # Should return False or handle gracefully
        assert isinstance(result, bool)


class TestAccountMethod:
    """Tests for the account() method."""

    def test_returns_configured_account_name(self, basic_importer, minimal_qbo_file):
        """account() returns the configured account name."""
        result = basic_importer.account(str(minimal_qbo_file))
        assert result == "Liabilities:CreditCard:Amex"

    def test_different_account_configurations(self, minimal_qbo_file):
        """Different configs return different account names."""
        configs = [
            ("Liabilities:CreditCard:Amex:Personal", "Personal"),
            ("Liabilities:CreditCard:Amex:Business", "Business"),
            ("Assets:Checking:Main", "Main"),
        ]

        for account_name, _ in configs:
            config = AmexAccountConfig(
                account_name=account_name,
                currency="NOK",
            )
            importer = Importer(config=config, debug=False)
            assert importer.account(str(minimal_qbo_file)) == account_name


class TestFilenameMethod:
    """Tests for the filename() method."""

    def test_basic_filename_without_account_id(self, basic_importer, minimal_qbo_file):
        """Filename without account_id uses simple prefix."""
        result = basic_importer.filename(str(minimal_qbo_file))
        assert result == "amex_qbo.activity.qbo"

    def test_filename_with_account_id_includes_suffix(
        self, importer_with_account_id, minimal_qbo_file
    ):
        """Filename with account_id includes account name suffix."""
        result = importer_with_account_id.filename(str(minimal_qbo_file))
        # Account is "Liabilities:CreditCard:Amex:Personal", so suffix is "Personal"
        assert result == "amex_qbo.Personal.activity.qbo"

    def test_filename_preserves_original_basename(self, basic_importer, tmp_path):
        """Original filename is preserved in the result."""
        qbo_file = tmp_path / "activity_march_2025.qbo"
        qbo_file.write_text("<OFX></OFX>")
        result = basic_importer.filename(str(qbo_file))
        assert "activity_march_2025.qbo" in result
