"""Locale-aware parsing of the amounts and dates printed on invoices."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as dateparser

AMOUNT = r"-?[£$€]?\s?\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\s?€?"
_EU = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}$")
SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}


def parse_amount(text: str | None) -> Decimal | None:
    """'1.234,56 €' -> 1234.56, '$1,234.56' -> 1234.56. A trailing ',dd' means a comma decimal."""
    if not text:
        return None
    s = re.sub(r"[^\d.,-]", "", text)
    neg = s.startswith("-")
    s = s.lstrip("-")
    if _EU.fullmatch(s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if neg else v


def parse_date(text: str | None, dayfirst: bool) -> date | None:
    if not text:
        return None
    try:
        return dateparser.parse(text.strip(), dayfirst=dayfirst, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def detect_currency(text: str) -> str | None:
    m = re.search(r"\b(USD|EUR|GBP)\b", text)
    if m:
        return m.group(1)
    for sym, code in SYMBOLS.items():
        if sym in text:
            return code
    return None
