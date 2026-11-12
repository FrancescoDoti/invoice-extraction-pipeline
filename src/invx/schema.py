"""The target schema every extractor must produce."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class Invoice(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    vendor_name: str | None = None
    currency: str | None = Field(None, description="ISO 4217 code, e.g. EUR")
    subtotal: Decimal | None = None
    discount: Decimal = Decimal("0")
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItem] = []


HEADER_FIELDS = ["invoice_number", "invoice_date", "due_date", "vendor_name", "currency", "subtotal", "discount", "tax", "total"]
