"""Data models for OFX/QBO file parsing."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class RawTransaction(BaseModel):
    """Raw transaction data extracted from QBO file."""
    date: str | None = None
    amount: str | None = None
    payee: str | None = None
    memo: str | None = None
    id: str | None = None
    type: str | None = None


class ParsedTransaction(BaseModel):
    """Processed transaction with proper types."""
    date: date
    amount: Decimal
    payee: str | None = None
    memo: str | None = ""
    id: str | None = None
    type: str | None = None

    @field_validator('amount', mode='before')
    @classmethod
    def validate_amount(cls, v):
        """Ensure amount is a valid decimal."""
        return Decimal(v) if isinstance(v, str) else v


class BeanTransaction(BaseModel):
    """Transaction ready for conversion to Beancount entries."""
    model_config = {"arbitrary_types_allowed": True}

    date: date
    amount: Decimal
    currency: str
    payee: str | None = None
    narration: str = ""
    flag: str = "*"
    tags: set[str] = Field(default_factory=set)
    links: set[str] = Field(default_factory=set)
    account: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    matched_account: str | None = None


class QboFileData(BaseModel):
    """Data extracted from a QBO file."""
    transactions: list[RawTransaction] = Field(default_factory=list)
    balance: str | None = None
    balance_date: date | None = None
    currency: str | None = None
    account_id: str | None = None
    organization: str | None = None
