from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator


class RawTransaction(BaseModel):
    """Raw transaction data extracted from QBO file."""
    date: Optional[str] = None
    amount: Optional[str] = None
    payee: Optional[str] = None
    memo: Optional[str] = None
    id: Optional[str] = None
    type: Optional[str] = None


class ParsedTransaction(BaseModel):
    """Processed transaction with proper types."""
    date: date
    amount: Decimal
    payee: Optional[str] = None
    memo: Optional[str] = ""
    id: Optional[str] = None
    type: Optional[str] = None
    
    @field_validator('amount', mode='before')
    @classmethod
    def validate_amount(cls, v):
        """Ensure amount is a valid decimal."""
        return Decimal(v) if isinstance(v, str) else v


class BeanTransaction(BaseModel):
    """Transaction ready for conversion to Beancount entries."""
    date: date
    amount: Decimal
    currency: str
    payee: Optional[str] = None
    narration: str = ""
    flag: str = "*"
    tags: Set[str] = Field(default_factory=set)
    links: Set[str] = Field(default_factory=set)
    account: str = ""
    metadata: Dict[str, str] = Field(default_factory=dict)
    matched_account: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True


class QboFileData(BaseModel):
    """Data extracted from a QBO file."""
    transactions: List[RawTransaction] = Field(default_factory=list)
    balance: Optional[str] = None
    balance_date: Optional[date] = None
    currency: Optional[str] = None
