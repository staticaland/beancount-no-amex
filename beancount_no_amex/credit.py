import datetime
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import beangulp
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
        currency: Optional[str] = None,
        narration_to_account_mappings: Optional[Sequence[Tuple[str, str]]] = None,
        flag: str = "*",
        debug: bool = True,
    ):
        """
        Initialize the American Express QBO importer.

        Args:
            account_name: The target account name in Beancount.
            currency: Optional default currency (will be auto-detected if not provided).
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

    def categorize_transaction(self, transaction_entry: data.Transaction, currency: str) -> data.Transaction:
        """
        Categorize transaction based on pattern matching in narration.

        Args:
            transaction_entry: The transaction to categorize.
            currency: The currency to use for the new posting.

        Returns:
            The modified transaction with added posting, if a pattern matched.
        """
        # If no categorization rules or no postings, return transaction unchanged
        if not self.narration_to_account_mappings or not transaction_entry.postings:
            return transaction_entry

        # Get the combined narration string to match against (payee and/or memo)
        narration = transaction_entry.narration or ""

        for pattern, account in self.narration_to_account_mappings:
            if pattern in narration:
                # Create a balancing posting with the opposite amount
                main_posting = transaction_entry.postings[0]
                opposite_units = Amount(-main_posting.units.number, currency)
                balancing_posting = data.Posting(
                    account, opposite_units, None, None, None, None
                )
                # Append the new posting
                new_postings = transaction_entry.postings + [balancing_posting]
                return transaction_entry._replace(postings=new_postings)

        return transaction_entry  # Return unchanged if no patterns match

    def extract(self, filepath: str, existing_entries: List[data.Directive]) -> List[data.Directive]:
        """Extract transactions from an American Express QBO file."""
        entries = []

        parsed_data = self._parse_qbo_file(filepath)
        transactions = parsed_data["transactions"]

        # Use file's currency if detected, otherwise fall back to default
        currency = parsed_data["currency"] or self.default_currency or "USD"

        if self.debug and parsed_data["currency"]:
            print(f"Detected currency: {parsed_data['currency']}")

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
            transaction_entry = data.Transaction(
                meta=meta,
                date=date,
                flag=self.flag,
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=[posting],
            )

            # Apply pattern-based categorization
            transaction_entry = self.categorize_transaction(transaction_entry, currency)

            entries.append(transaction_entry)

        # Add balance assertion if available
        if parsed_data["balance"] is not None:
            bal_amount = D(str(parsed_data["balance"]))

            # Determine the date for the balance assertion
            if parsed_data["balance_date"]:
                bal_date = parsed_data["balance_date"]
            elif transactions:
                # If no explicit balance date, use the day after the latest transaction
                latest_date = max(t["date"] for t in transactions)
                bal_date = latest_date + datetime.timedelta(days=1)
            else:
                bal_date = datetime.date.today()

            # Create the balance assertion
            meta = data.new_metadata(filepath, 0)
            balance_entry = data.Balance(
                meta=meta,
                date=bal_date,
                account=self.account_name,
                amount=Amount(bal_amount, currency),
                tolerance=None,
                diff_amount=None
            )

            entries.append(balance_entry)

        return entries
