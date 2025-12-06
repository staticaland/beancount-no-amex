import datetime
import traceback
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple
from dataclasses import dataclass, field

import beangulp
from beangulp.testing import main as test_main
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from lxml import etree
from pydantic import ValidationError

from beancount_no_amex.models import BeanTransaction, ParsedTransaction, QboFileData, RawTransaction


# Added dataclass definition
@dataclass
class AmexAccountConfig:
    """Configuration for an American Express QBO account."""
    account_name: str
    currency: str
    narration_to_account_mappings: List[Tuple[str, str]] = field(default_factory=list)


def parse_ofx_time(date_str: str) -> datetime.datetime:
    """Parse an OFX time string and return a datetime object.

    Args:
        date_str: A string, the date to be parsed in YYYYMMDD or YYYYMMDDHHMMSS format.
    Returns:
        A datetime.datetime instance.
    """
    if len(date_str) < 14:
        return datetime.datetime.strptime(date_str[:8], '%Y%m%d')
    return datetime.datetime.strptime(date_str[:14], '%Y%m%d%H%M%S')


def find_currency(tree) -> Optional[str]:
    """Find the currency specified in the OFX file.

    Args:
        tree: An lxml ElementTree object
    Returns:
        A string with the currency code, or None if not found
    """
    # Look for CURDEF tags in statement response sections
    for stmt_type in ['STMTRS', 'CCSTMTRS', 'INVSTMTRS']:
        curdef_elements = tree.xpath(f".//*[contains(local-name(), '{stmt_type}')]/CURDEF")
        for element in curdef_elements:
            if element.text and element.text.strip():
                return element.text.strip()

    # If not found in statement sections, try finding any CURDEF tag
    curdef_elements = tree.xpath(".//CURDEF")
    for element in curdef_elements:
        if element.text and element.text.strip():
            return element.text.strip()

    return None


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
        self.narration_to_account_mappings = config.narration_to_account_mappings
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

    def _determine_currency(self, file_currency: Optional[str]) -> str:
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

        # Default currency should never be None as it defaults to "NOK" in __init__,
        # but as a safety measure, fallback to "USD" if somehow it is None
        return self.currency or "NOK"

    def identify(self, filepath: str) -> bool:
        """Check if the file is an American Express QBO statement."""
        path = Path(filepath)

        # Check file extension first (quick check)
        if path.suffix.lower() != ".qbo":
            return False

        # Check for compatible MIME types
        mime_type = beangulp.mimetypes.guess_type(filepath, strict=False)[0]
        if mime_type not in {
            'application/x-ofx',
            'application/vnd.intu.qbo',
            'application/vnd.intu.qfx'
        }:
            return False

        # Check for Amex-specific filename pattern
        if path.name.lower().startswith("activity"):
            return True

        return False

    def account(self, filepath: str) -> str:
        """Return the account name for the file."""
        return self.account_name

    def filename(self, filepath: str) -> str:
        """Generate a descriptive filename for the imported data."""
        return f"amex_qbo.{Path(filepath).name}"

    def date(self, filepath: str) -> Optional[datetime.date]:
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

    def finalize(self, txn: data.Transaction, row: Any) -> Optional[data.Transaction]:
        """
        Post-process the transaction with categorization based on narration.

        Args:
            txn: The transaction object to finalize.
            row: The original transaction data from the QBO file.

        Returns:
            The modified transaction, or None if invalid.
        """
        # If no categorization rules or no postings, return transaction unchanged
        if not self.narration_to_account_mappings or not txn.postings:
            return txn  # No changes if no mappings or postings

        for pattern, account in self.narration_to_account_mappings:
            if pattern in txn.narration:
                # Create a balancing posting with the opposite amount
                opposite_units = Amount(-txn.postings[0].units.number, txn.postings[0].units.currency)
                balancing_posting = data.Posting(
                    account, opposite_units, None, None, None, None
                )
                # Append the new posting
                return txn._replace(postings=txn.postings + [balancing_posting])
        return txn  # Return unchanged if no patterns match

    def extract(self, filepath: str, existing_entries: List[data.Directive]) -> List[data.Directive]:
        """
        Extract transactions from an American Express QBO file.

        Currency is determined by first checking the QBO file, and falling back
        to the currency specified in the importer configuration.

        Args:
            filepath: Path to the QBO file
            existing_entries: Existing directives (used for potential deduplication)

        Returns:
            List of extracted Beancount directives (Transactions and Balance).
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

        # 3. Process each raw transaction
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
                    amount_decimal = D(str(amount_str))
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
                balance_decimal = D(str(qbo_data.balance))
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

        # (Optional: Add deduplication logic here if needed in the future)
        # from beangulp import extract, similar
        # comparator = similar.heuristic_comparator(...)
        # extract.mark_duplicate_entries(entries, existing_entries, ...)

        return entries

def main():
    """Entry point for the command-line interface."""
    # This enables the testing CLI commands
    test_main(Importer(
        AmexAccountConfig(
            account_name='Liabilities:CreditCard:Amex',
            currency='NOK',
            narration_to_account_mappings=[
                ('GITHUB', 'Expenses:Cloud-Services:Source-Hosting:Github'),
                ('Fedex', 'Expenses:Postage:FedEx'),
                ('FREMTIND', 'Expenses:Insurance'),
                ('Meny Alna Oslo', 'Expenses:Groceries'),
                ('VINMONOPOLET', 'Expenses:Groceries'),
            ]
        )
    ))

if __name__ == '__main__':
    main()
