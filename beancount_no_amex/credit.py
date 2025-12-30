import datetime
import traceback
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

import beangulp
from beangulp import Ingest
from beangulp.testing import main as test_main
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from lxml import etree
from pydantic import ValidationError

from beancount_no_amex.models import (
    BeanTransaction,
    ParsedTransaction,
    QboFileData,
    RawTransaction,
    TransactionPattern,
)

# Constants
DEFAULT_CURRENCY = "NOK"
OFX_DATE_FORMAT = "%Y%m%d"
OFX_DATETIME_FORMAT = "%Y%m%d%H%M%S"
OFX_STATEMENT_TYPES = ("STMTRS", "CCSTMTRS", "INVSTMTRS")
VALID_MIME_TYPES = frozenset({
    "application/x-ofx",
    "application/vnd.intu.qbo",
    "application/vnd.intu.qfx",
})


@dataclass
class AmexAccountConfig:
    """Configuration for an American Express QBO account.

    Attributes:
        account_name: The Beancount account name (e.g., 'Liabilities:CreditCard:Amex:Personal')
        currency: Default currency for transactions (e.g., 'NOK')
        account_id: Optional QBO account ID for matching specific cards (e.g., 'XYZ|98765').
                    When set, the importer will only match files with this exact ACCTID.
                    When None, the importer matches any Amex QBO file.
        narration_to_account_mappings: List of (pattern, account) tuples for simple substring
                    matching (legacy, backward-compatible). Pattern matches anywhere in narration.
        transaction_patterns: List of TransactionPattern objects for advanced pattern matching.
                    Supports regex, case-insensitive matching, and amount-based conditions.
                    These patterns are checked AFTER narration_to_account_mappings.
        skip_deduplication: When True, skip FITID-based deduplication (default: False).
                           Useful for forcing re-import of transactions.

    Example with transaction_patterns:
        from beancount_no_amex.models import TransactionPattern, AmountCondition, AmountOperator
        from decimal import Decimal

        config = AmexAccountConfig(
            account_name='Liabilities:CreditCard:Amex',
            currency='NOK',
            transaction_patterns=[
                # Regex match with case insensitivity
                TransactionPattern(
                    narration=r"REMA\\s*1000",
                    regex=True,
                    case_insensitive=True,
                    account="Expenses:Groceries"
                ),
                # Amount-only match (small purchases)
                TransactionPattern(
                    amount_condition=AmountCondition(
                        operator=AmountOperator.LT,
                        value=Decimal("50")
                    ),
                    account="Expenses:PettyCash"
                ),
                # Combined: merchant + amount range
                TransactionPattern(
                    narration="VINMONOPOLET",
                    amount_condition=AmountCondition(
                        operator=AmountOperator.GT,
                        value=Decimal("500")
                    ),
                    account="Expenses:Entertainment:Alcohol:Expensive"
                ),
            ],
        )
    """
    account_name: str
    currency: str
    account_id: str | None = None
    narration_to_account_mappings: list[tuple[str, str]] = field(default_factory=list)
    transaction_patterns: list[TransactionPattern] = field(default_factory=list)
    skip_deduplication: bool = False


def parse_ofx_time(date_str: str) -> datetime.datetime:
    """Parse an OFX time string and return a datetime object.

    Args:
        date_str: A string, the date to be parsed in YYYYMMDD or YYYYMMDDHHMMSS format.
    Returns:
        A datetime.datetime instance.
    """
    if len(date_str) < 14:
        return datetime.datetime.strptime(date_str[:8], OFX_DATE_FORMAT)
    return datetime.datetime.strptime(date_str[:14], OFX_DATETIME_FORMAT)


def find_account_id(filepath: str) -> str | None:
    """Quickly extract the account ID from a QBO file without full parsing.

    Args:
        filepath: Path to the QBO file
    Returns:
        The account ID string, or None if not found
    """
    try:
        parser = etree.XMLParser(recover=True)
        with open(filepath, "rb") as f:
            tree = etree.parse(f, parser)

        acct_from = tree.find(".//CCACCTFROM")
        if acct_from is None:
            acct_from = tree.find(".//BANKACCTFROM")
        if acct_from is not None:
            acct_id = acct_from.findtext("ACCTID")
            if acct_id:
                return acct_id.strip()
    except Exception:
        pass
    return None


def find_currency(tree) -> str | None:
    """Find the currency specified in the OFX file.

    Args:
        tree: An lxml ElementTree object
    Returns:
        A string with the currency code, or None if not found
    """
    # Look for CURDEF tags in statement response sections
    for stmt_type in OFX_STATEMENT_TYPES:
        for elem in tree.xpath(f".//*[contains(local-name(), '{stmt_type}')]/CURDEF"):
            if text := (elem.text or "").strip():
                return text

    # Fallback: find any CURDEF tag in the document
    return next(
        (elem.text.strip() for elem in tree.xpath(".//CURDEF") if elem.text and elem.text.strip()),
        None,
    )


class Importer(beangulp.Importer):
    """Importer for American Express QBO statements."""

    def __init__(
        self,
        config: AmexAccountConfig,  # Accept config object
        flag: str = "*",
        debug: bool = True,
    ):
        """
        Initialize the American Express QBO importer using a configuration object.

        Args:
            config: An AmexAccountConfig object with account details.
            flag: Transaction flag (default: "*").
            debug: Enable debug output (default: True).
        """
        # Store configuration values from the config object
        self.account_name = config.account_name
        self.currency = config.currency  # Store configured currency
        self.account_id = config.account_id  # Optional account ID for matching
        self.narration_to_account_mappings = config.narration_to_account_mappings
        self.transaction_patterns = config.transaction_patterns
        self.skip_deduplication = config.skip_deduplication
        self.flag = flag
        self.debug = debug

    def _parse_qbo_file(self, filepath: str) -> QboFileData:
        """Parse the QBO file and extract transactions and balance info using lxml."""
        result = QboFileData()
        try:
            # Parse the file with recovery mode for potentially malformed XML
            parser = etree.XMLParser(recover=True)
            with open(filepath, "rb") as f:
                tree = etree.parse(f, parser)

            # Extract account ID from CCACCTFROM or BANKACCTFROM
            acct_from = tree.find(".//CCACCTFROM")
            if acct_from is None:
                acct_from = tree.find(".//BANKACCTFROM")
            if acct_from is not None:
                acct_id = acct_from.findtext("ACCTID")
                if acct_id:
                    result.account_id = acct_id.strip()

            # Extract organization info (e.g., "AMEX")
            fi_elem = tree.find(".//FI")
            if fi_elem is not None:
                org = fi_elem.findtext("ORG")
                if org:
                    result.organization = org.strip()

            # Extract currency information
            result.currency = find_currency(tree)

            # Extract balance information
            ledger_bal = tree.find(".//LEDGERBAL")
            if ledger_bal is not None:
                bal_amt = ledger_bal.findtext("BALAMT")
                if bal_amt:
                    result.balance = bal_amt

                    # Try to get the balance date if available
                    dtasof = ledger_bal.findtext("DTASOF")
                    if dtasof:
                        try:
                            # Use the parse_ofx_time function
                            result.balance_date = parse_ofx_time(dtasof).date()
                        except ValueError:
                            pass

            # Find all <STMTTRN> elements
            stmttrn_elements = tree.findall(".//STMTTRN")

            for idx, element in enumerate(stmttrn_elements, 1):
                # Extract key fields
                dtposted = element.findtext("DTPOSTED")
                trnamt = element.findtext("TRNAMT")
                name = element.findtext("NAME")
                memo = element.findtext("MEMO")
                fitid = element.findtext("FITID")
                trntype = element.findtext("TRNTYPE")

                # Create raw transaction
                raw_txn = RawTransaction(
                    date=dtposted,
                    amount=trnamt or "0.00",
                    payee=name.strip() if name else None,
                    memo=(memo or "").strip(),
                    id=fitid,
                    type=trntype,
                )
                
                result.transactions.append(raw_txn)

            return result

        except etree.XMLSyntaxError as e:
            if self.debug:
                print(f"XML syntax error: {e}")
            return QboFileData()
        except Exception as e:
            if self.debug:
                print(f"Error parsing QBO file: {traceback.format_exc()}")
            return QboFileData()

    def _determine_currency(self, file_currency: str | None) -> str:
        """
        Determine which currency to use for transactions based on priority:
        1. Currency extracted from file (if available)
        2. Default currency specified during initialization
        3. "NOK" as last fallback

        Args:
            file_currency: Currency extracted from the QBO file, or None if not found

        Returns:
            The currency code to use for transactions
        """
        if file_currency:
            if self.debug:
                print(f"Using currency from file: {file_currency}")
            return file_currency

        if self.debug:
            print(f"File currency not found, using default: {self.currency}")

        # Default currency should never be None, but use DEFAULT_CURRENCY as fallback
        return self.currency or DEFAULT_CURRENCY

    def _extract_existing_fitids(self, existing_entries: list[data.Directive]) -> set[str]:
        """Extract all FITIDs from existing entries for deduplication.

        Scans the existing ledger entries for transactions that have an 'id'
        metadata field (containing the FITID) and returns them as a set for
        efficient lookup during import.

        Args:
            existing_entries: List of existing Beancount directives from the ledger.

        Returns:
            Set of FITID strings found in existing transactions.
        """
        existing_fitids: set[str] = set()
        for entry in existing_entries:
            if isinstance(entry, data.Transaction):
                fitid = entry.meta.get("id")
                if fitid:
                    existing_fitids.add(fitid)
        return existing_fitids

    def identify(self, filepath: str) -> bool:
        """Check if the file is an American Express QBO statement.

        When account_id is configured, also verifies that the file's ACCTID matches.
        This enables multiple importers to handle different Amex accounts.
        """
        path = Path(filepath)
        mime_type = beangulp.mimetypes.guess_type(filepath, strict=False)[0]

        # Basic file type validation
        is_qbo_file = (
            path.suffix.lower() == ".qbo"
            and mime_type in VALID_MIME_TYPES
            and path.name.lower().startswith("activity")
        )

        if not is_qbo_file:
            return False

        # If no account_id configured, match any Amex QBO file
        if self.account_id is None:
            return True

        # Match specific account ID
        file_account_id = find_account_id(filepath)
        return file_account_id == self.account_id

    def account(self, filepath: str) -> str:
        """Return the account name for the file."""
        return self.account_name

    def filename(self, filepath: str) -> str:
        """Generate a descriptive filename for the imported data.

        When account_id is configured, includes the account suffix for disambiguation.
        E.g., 'amex_qbo.Personal.activity.qbo' for 'Liabilities:CreditCard:Amex:Personal'
        """
        base_name = Path(filepath).name
        if self.account_id:
            # Use last component of account name for disambiguation
            account_suffix = self.account_name.split(":")[-1]
            return f"amex_qbo.{account_suffix}.{base_name}"
        return f"amex_qbo.{base_name}"

    def date(self, filepath: str) -> datetime.date | None:
        """Extract the latest transaction date from the file."""
        parsed_data = self._parse_qbo_file(filepath)
        
        # Convert raw transactions to parsed transactions
        parsed_transactions = []
        for raw_txn in parsed_data.transactions:
            try:
                if raw_txn.date:
                    date_val = parse_ofx_time(raw_txn.date).date()
                    parsed_txn = ParsedTransaction(
                        date=date_val,
                        amount=raw_txn.amount or "0.00",
                        payee=raw_txn.payee,
                        memo=raw_txn.memo,
                        id=raw_txn.id,
                        type=raw_txn.type
                    )
                    parsed_transactions.append(parsed_txn)
            except (ValueError, ValidationError):
                continue

        if not parsed_transactions:
            return datetime.date.today()

        latest_date = max(t.date for t in parsed_transactions)
        return latest_date

    def finalize(self, txn: data.Transaction, row: Any) -> data.Transaction | None:
        """
        Post-process the transaction with categorization based on narration and/or amount.

        Matching is done in two phases:
        1. Legacy narration_to_account_mappings (simple substring matching)
        2. Advanced transaction_patterns (regex, case-insensitive, amount conditions)

        The first matching pattern wins. If a match is found in phase 1, phase 2 is skipped.

        Args:
            txn: The transaction object to finalize.
            row: The original transaction data from the QBO file.

        Returns:
            The modified transaction, or None if invalid.
        """
        # If no postings, return transaction unchanged
        if not txn.postings:
            return txn

        # No categorization rules defined
        if not self.narration_to_account_mappings and not self.transaction_patterns:
            return txn

        # Get the primary posting amount for pattern matching
        amount = txn.postings[0].units.number
        narration = txn.narration or ""

        # Phase 1: Legacy simple substring matching
        for pattern, account in self.narration_to_account_mappings:
            if pattern in narration:
                return self._add_balancing_posting(txn, account)

        # Phase 2: Advanced pattern matching
        for pattern in self.transaction_patterns:
            if pattern.matches(narration, amount):
                return self._add_balancing_posting(txn, pattern.account)

        return txn  # Return unchanged if no patterns match

    def _add_balancing_posting(
        self, txn: data.Transaction, account: str
    ) -> data.Transaction:
        """Add a balancing posting to the transaction.

        Args:
            txn: The transaction to modify.
            account: The target account for the balancing posting.

        Returns:
            The transaction with the balancing posting added.
        """
        opposite_units = Amount(
            -txn.postings[0].units.number, txn.postings[0].units.currency
        )
        balancing_posting = data.Posting(account, opposite_units, None, None, None, None)
        return txn._replace(postings=txn.postings + [balancing_posting])

    def extract(self, filepath: str, existing_entries: list[data.Directive]) -> list[data.Directive]:
        """
        Extract transactions from an American Express QBO file.

        Currency is determined by first checking the QBO file, and falling back
        to the currency specified in the importer configuration.

        Deduplication is performed using FITID (Financial Transaction ID) matching.
        Transactions with FITIDs that already exist in the ledger are skipped.
        This can be disabled by setting skip_deduplication=True in the config.

        Args:
            filepath: Path to the QBO file
            existing_entries: Existing directives from the ledger, used for
                             FITID-based deduplication.

        Returns:
            List of extracted Beancount directives (Transactions and Balance),
            excluding any duplicates found in existing_entries.
        """
        entries = []

        # 1. Parse the QBO file content
        qbo_data = self._parse_qbo_file(filepath)
        if not qbo_data:  # Check if parsing returned data
            if self.debug:
                print(f"Skipping file {filepath} due to parsing errors or empty content.")
            return []

        # 2. Determine the currency to use
        currency = self._determine_currency(qbo_data.currency)

        # 3. Extract existing FITIDs for deduplication
        existing_fitids: set[str] = set()
        skipped_duplicates = 0
        if not self.skip_deduplication:
            existing_fitids = self._extract_existing_fitids(existing_entries)
            if self.debug and existing_fitids:
                print(f"Found {len(existing_fitids)} existing FITIDs for deduplication")

        # 4. Process each raw transaction
        for idx, raw_txn in enumerate(qbo_data.transactions, 1):
            try:
                # 3a. Validate and parse essential raw data
                if not raw_txn.date:
                    if self.debug:
                        print(f"Skipping transaction {idx} in {filepath} due to missing date.")
                    continue

                txn_date = parse_ofx_time(raw_txn.date).date()
                amount_str = raw_txn.amount or "0.00"
                payee = raw_txn.payee
                memo = raw_txn.memo or ""
                txn_id = raw_txn.id
                txn_type = raw_txn.type

                # 4a. Check for duplicate FITID
                if txn_id and txn_id in existing_fitids:
                    skipped_duplicates += 1
                    if self.debug:
                        print(f"Skipping duplicate transaction {idx} (FITID: {txn_id})")
                    continue

                # Use payee as narration, fallback to memo if payee is missing
                narration = payee or memo
                metadata = data.new_metadata(filepath, idx) # Start with standard metadata

                # Add specific metadata if available
                if txn_id:
                    metadata["id"] = txn_id
                if txn_type:
                    metadata["type"] = txn_type
                # Add memo to metadata only if it's not already used as narration
                if memo and payee:
                    metadata["memo"] = memo

                # 3c. Create the primary posting for the credit card account
                try:
                    # Convert amount string to Decimal
                    amount_decimal = D(amount_str)
                except Exception as e:
                     if self.debug:
                         print(f"Skipping transaction {idx} in {filepath} due to invalid amount '{amount_str}': {e}")
                     continue

                amount_obj = Amount(amount_decimal, currency)
                primary_posting = data.Posting(
                    self.account_name, amount_obj, None, None, None, None
                )

                # 3d. Create the initial Beancount transaction (without balancing posting yet)
                txn = data.Transaction(
                    meta=metadata,
                    date=txn_date,
                    flag=self.flag,
                    payee=payee, # Keep original payee (can be None)
                    narration=narration,
                    tags=data.EMPTY_SET, # Initialize tags/links
                    links=data.EMPTY_SET,
                    postings=[primary_posting],
                )

                # 3e. Apply finalization logic (adds balancing posting)
                finalized_txn = self.finalize(txn, raw_txn) # Pass raw_txn for context

                # Skip if finalization failed or indicated skipping
                if finalized_txn is None:
                    if self.debug:
                        print(f"Skipping transaction {idx} in {filepath} after finalization.")
                    continue

                # 3f. Add the completed transaction to the list
                entries.append(finalized_txn)

            except (ValueError, ValidationError) as e: # Catch known parsing/validation errors
                if self.debug:
                    print(f"Error processing transaction {idx} in {filepath}: {e}\nRaw data: {raw_txn}")
                continue
            except Exception as e: # Catch unexpected errors during processing
                 if self.debug:
                     print(f"Unexpected error processing transaction {idx} in {filepath}: {e}\n{traceback.format_exc()}")
                 continue # Skip to next transaction

        # 4. Add balance assertion if available
        if qbo_data.balance is not None and qbo_data.balance_date:
            try:
                balance_decimal = D(qbo_data.balance)
                # QBO balance is typically the balance *at the end* of the statement date.
                # Beancount balance assertion applies at the *start* of the day.
                # So, we assert the balance for the day *after* the statement balance date.
                balance_assertion_date = qbo_data.balance_date + datetime.timedelta(days=1)

                balance_amount = Amount(balance_decimal, currency)
                balance_meta = data.new_metadata(filepath, 0) # Metadata for balance assertion

                balance_entry = data.Balance(
                    meta=balance_meta,
                    date=balance_assertion_date,
                    account=self.account_name,
                    amount=balance_amount,
                    tolerance=None, # Default tolerance
                    diff_amount=None
                )
                entries.append(balance_entry)
                if self.debug:
                    print(f"Added balance assertion for {self.account_name} on {balance_assertion_date}: {balance_amount}")

            except Exception as e: # Catch potential errors creating balance assertion
                 if self.debug:
                     print(f"Could not create balance assertion for {filepath}: {e}")

        # 6. Report deduplication results
        if self.debug and skipped_duplicates > 0:
            print(f"Deduplication: skipped {skipped_duplicates} duplicate transaction(s)")

        return entries

def get_importers() -> list[beangulp.Importer]:
    """Create and return a list of configured importers.

    This function demonstrates how to configure multiple Amex account importers.
    Each importer can be configured with:
    - A unique account_id to match specific QBO files
    - Different account names for different cards
    - Separate categorization rules per account

    Example with multiple accounts:
        return [
            Importer(AmexAccountConfig(
                account_name='Liabilities:CreditCard:Amex:Personal',
                currency='NOK',
                account_id='XYZ|12345',  # Personal card account ID
                narration_to_account_mappings=[
                    ('VINMONOPOLET', 'Expenses:Groceries'),
                    ('SPOTIFY', 'Expenses:Entertainment:Music'),
                ],
            )),
            Importer(AmexAccountConfig(
                account_name='Liabilities:CreditCard:Amex:Business',
                currency='NOK',
                account_id='XYZ|67890',  # Business card account ID
                narration_to_account_mappings=[
                    ('GITHUB', 'Expenses:Business:Software'),
                    ('AWS', 'Expenses:Business:Cloud'),
                ],
            )),
        ]
    """
    # Default configuration - single importer without account_id filtering
    # Matches any Amex QBO file
    return [
        Importer(AmexAccountConfig(
            account_name='Liabilities:CreditCard:Amex',
            currency='NOK',
            # account_id='XYZ|98765',  # Uncomment and set to match specific card
            narration_to_account_mappings=[
                ('GITHUB', 'Expenses:Cloud-Services:Source-Hosting:Github'),
                ('Fedex', 'Expenses:Postage:FedEx'),
                ('FREMTIND', 'Expenses:Insurance'),
                ('Meny Alna Oslo', 'Expenses:Groceries'),
                ('VINMONOPOLET', 'Expenses:Groceries'),
            ],
        )),
    ]


def main():
    """Entry point for the command-line interface.

    Uses beangulp.Ingest for full importer workflow support:
    - identify: Check which files match which importers
    - extract: Extract transactions to beancount format
    - file: Organize source documents (when implemented)
    - archive: Move processed files (when implemented)

    For testing, run: beancount-no-amex test test_data/
    """
    importers = get_importers()

    # Use Ingest for full beangulp workflow (supports multiple importers)
    ingest = Ingest(importers)
    ingest.main()


def test_main_single():
    """Alternative entry point for single-importer testing.

    This uses beangulp's testing.main which is simpler but only supports
    a single importer. Useful for development and basic testing.
    """
    importers = get_importers()
    if importers:
        test_main(importers[0])


if __name__ == '__main__':
    main()
