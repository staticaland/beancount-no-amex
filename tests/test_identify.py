"""Component tests for file identification (identify method).

The identify() method determines if a file should be processed by this importer.
It checks:
1. File extension (.qbo) as a cheap pre-filter
2. OFX content markers (OFXHEADER, <OFX, statement types)
3. Account ID matching (for multi-account support)

Identification is deliberately independent of the file's name (beyond the
extension) and of mimetype guesses, both of which reject legitimately
renamed exports.
"""

from pathlib import Path

from beancount_no_amex.credit import Config, Importer


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

    def test_accepts_any_filename_with_ofx_content(self, basic_importer, tmp_path):
        """Accepts .qbo files regardless of their base name."""
        for name in ("statement.qbo", "Activity.qbo", "activity_2025-03.qbo",
                     "2025-01.qbo"):
            qbo_file = tmp_path / name
            qbo_file.write_text("<?xml version='1.0'?><OFX></OFX>")
            assert basic_importer.identify(str(qbo_file)) is True, name

    def test_rejects_qbo_file_without_ofx_content(self, basic_importer, tmp_path):
        """Rejects .qbo files whose content is not OFX."""
        qbo_file = tmp_path / "activity.qbo"
        qbo_file.write_text("Dato;Beskrivelse;Inn;Ut\n01.01.2025;KIWI;;100,00\n")
        assert basic_importer.identify(str(qbo_file)) is False

    def test_identifies_monthly_export_fixture(self, basic_importer):
        """Identifies a monthly export in XML-declaration style.

        Regression test: exports named by period (e.g. 2025-01.qbo) with an
        XML declaration before the OFX processing instruction — the format
        used by the beancounters demo dataset — must identify without any
        subclass workaround.
        """
        fixture = Path(__file__).parent / "fixtures" / "monthly_export.qbo"
        assert basic_importer.identify(str(fixture)) is True


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

        config = Config(
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
            config=Config(
                account_name="Liabilities:CreditCard:Amex:Personal",
                currency="NOK",
                account_id="PERSONAL|111",
            ),
            debug=False,
        )
        business_importer = Importer(
            config=Config(
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
        """Rejects empty files (no OFX content)."""
        empty_file = tmp_path / "activity.qbo"
        empty_file.write_text("")
        assert basic_importer.identify(str(empty_file)) is False

    def test_binary_garbage_file(self, basic_importer, tmp_path):
        """Rejects binary garbage."""
        garbage_file = tmp_path / "activity.qbo"
        garbage_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")
        assert basic_importer.identify(str(garbage_file)) is False


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
            config = Config(
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
