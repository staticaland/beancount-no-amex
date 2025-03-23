import datetime
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import beangulp
from beangulp.testing import main as test_main
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from lxml import etree


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
        account_name: str,
        currency: str = "NOK",
        narration_to_account_mappings: Optional[Sequence[Tuple[str, str]]] = None,
        flag: str = "*",
        debug: bool = True,
    ):
        """
        Initialize the American Express QBO importer.

        Args:
            account_name: The target account name in Beancount.
            currency: Default currency to use when not auto-detected from file. Defaults to 'NOK'.
            narration_to_account_mappings: Optional list of (pattern, account) tuples
                to map narration patterns to accounts for categorization.
            flag: Transaction flag (default: "*").
            debug: Enable debug output (default: True).
        """
        self.account_name = account_name
        self.default_currency = currency  # Store as default currency
        self.narration_to_account_mappings = narration_to_account_mappings or []
        self.flag = flag
        self.debug = debug

    def _parse_qbo_file(self, filepath: str) -> Dict:
        """Parse the QBO file and extract transactions and balance info using lxml."""
        result = {
            "transactions": [],
            "balance": None,
            "balance_date": None,
            "currency": None  # Added currency to the result
        }

        try:
            # Parse the file with recovery mode for potentially malformed XML
            parser = etree.XMLParser(recover=True)
            with open(filepath, "rb") as f:
                tree = etree.parse(f, parser)

            # Extract currency information
            result["currency"] = find_currency(tree)

            # Extract balance information
            ledger_bal = tree.find(".//LEDGERBAL")
            if ledger_bal is not None:
                bal_amt = ledger_bal.findtext("BALAMT")
                if bal_amt:
                    result["balance"] = bal_amt

                    # Try to get the balance date if available
                    dtasof = ledger_bal.findtext("DTASOF")
                    if dtasof:
                        try:
                            # Use the parse_ofx_time function
                            result["balance_date"] = parse_ofx_time(dtasof).date()
                        except ValueError:
                            pass

            # Find all <STMTTRN> elements
            stmttrn_elements = tree.findall(".//STMTTRN")

            for idx, element in enumerate(stmttrn_elements, 1):
                transaction = {}

                # Extract key fields
                dtposted = element.findtext("DTPOSTED")
                trnamt = element.findtext("TRNAMT")
                name = element.findtext("NAME")
                memo = element.findtext("MEMO")
                fitid = element.findtext("FITID")
                trntype = element.findtext("TRNTYPE")

                # Date parsing using parse_ofx_time
                if dtposted:
                    try:
                        transaction["date"] = parse_ofx_time(dtposted).date()
                    except ValueError:
                        continue
                else:
                    continue

                # Amount
                transaction["amount"] = trnamt if trnamt else "0.00"

                # Payee and Memo (optional)
                transaction["payee"] = name.strip() if name else None
                transaction["memo"] = memo.strip() if memo else ""

                # Optional fields for metadata
                transaction["id"] = fitid if fitid else None
                transaction["type"] = trntype if trntype else None

                result["transactions"].append(transaction)

            return result

        except etree.XMLSyntaxError as e:
            if self.debug:
                print(f"XML syntax error: {e}")
            return {"transactions": [], "balance": None, "balance_date": None, "currency": None}
        except Exception as e:
            if self.debug:
                print(f"Error parsing QBO file: {traceback.format_exc()}")
            return {"transactions": [], "balance": None, "balance_date": None, "currency": None}

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
            print(f"File currency not found, using default: {self.default_currency}")

        # Default currency should never be None as it defaults to "NOK" in __init__,
        # but as a safety measure, fallback to "USD" if somehow it is None
        return self.default_currency or "NOK"

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
        transactions = parsed_data["transactions"]

        if not transactions:
            return datetime.date.today()

        latest_date = max(t["date"] for t in transactions)
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
                print("herrrooooo")
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

        Currency is determined with the following priority:
        1. Currency from the QBO file if available
        2. Default currency specified in constructor (defaults to 'NOK')
        3. 'USD' as a last-resort fallback

        Args:
            filepath: Path to the QBO file
            existing_entries: Existing directives

        Returns:
            List of extracted directives
        """
        entries = []

        parsed_data = self._parse_qbo_file(filepath)
        transactions = parsed_data["transactions"]

        # Use the helper method to determine currency
        currency = self._determine_currency(parsed_data["currency"])

        for idx, transaction in enumerate(transactions, 1):
            date = transaction["date"]
            payee = transaction["payee"]
            memo = transaction["memo"]
            narration = payee or ""

            # Metadata
            meta = data.new_metadata(filepath, idx)
            if transaction["id"]:
                meta["id"] = transaction["id"]
            if transaction["type"]:
                meta["type"] = transaction["type"]
            if memo:
                meta["memo"] = memo

            # Amount (inverted for credit card)
            amount = D(str(transaction["amount"]))
            amount_obj = Amount(amount, currency)
            posting = data.Posting(self.account_name, amount_obj, None, None, None, None)

            # Create transaction
            txn = data.Transaction(
                meta=meta,
                date=date,
                flag=self.flag,
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=[posting],
            )

            txn = self.finalize(txn, transaction)

            # Skip if finalize returned None
            if txn is None:
                continue

            entries.append(txn)

        return entries

if __name__ == '__main__':
    # This enables the testing CLI commands
    test_main(Importer(
        'Liabilities:CreditCard:Amex',
        narration_to_account_mappings=[
            ('GITHUB', 'Expenses:Cloud-Services:Source-Hosting:Github'),
            ('Fedex', 'Expenses:Postage:FedEx'),
            ('FREMTIND', 'Expenses:Insurance'),
            ('Meny Alna Oslo', 'Expenses:Groceries'),
            ('ANDERS', 'Expenses:Groceries'),
        ]
    ))
