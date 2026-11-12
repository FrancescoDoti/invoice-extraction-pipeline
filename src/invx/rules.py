"""Rule-based extractor, written against the classic, european and modern layouts only.

It is the cheap, fast, deterministic first stage. Its job is not to handle every
template: the validator decides whether its output can be trusted.
"""
import re

from .parsing import AMOUNT, detect_currency, parse_amount, parse_date
from .schema import Invoice, LineItem

NUMBER = re.compile(r"(?:Invoice No:|Invoice #|Bill Number)\s*(\S+)", re.I)
ISSUED = re.compile(r"(?:^Date:|Issue date:|Issued)\s*([^·\n]+?)(?:\s+[·-]\s+Due.*)?$", re.M | re.I)
DUE = re.compile(r"(?:Due Date:|Payment due:|[·-] Due)\s*([^\n]+)", re.I)
TOTALS = {
    "subtotal": re.compile(rf"^(?:Subtotal|Net amount)\s+({AMOUNT})$", re.M),
    "discount": re.compile(rf"^Discount\s+({AMOUNT})$", re.M),
    "tax": re.compile(rf"^(?:VAT|Tax)\b.*?\s({AMOUNT})$", re.M),
    "total": re.compile(rf"^(?:Total|Amount due|Grand Total)\s+({AMOUNT})$", re.M),
}
LINE = re.compile(rf"^(.+?)\s+(\d+(?:\.\d+)?)\s+({AMOUNT})\s+({AMOUNT})$")
HEADER_ROW = re.compile(r"^(Description|Item|Service)\b")
STOP_ROW = re.compile(r"^(Subtotal|Net amount)\b")


def clean_ocr(text: str) -> str:
    """Undo the most common OCR artefacts of table scans: grid lines read as | or quotes."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"[|\[\]]", " ", line)
        line = re.sub(r"^[\"'“”‘’_~.,:;-]+\s*", "", line.strip())
        line = re.sub(r"(\d)\s*[-_—]+$", r"\1", line)        # trailing rule fragments
        line = re.sub(r"(\d)\s+€", r"\1 €", line)
        out.append(re.sub(r"\s{2,}", " ", line).strip())
    return "\n".join(out)


def extract_rules(text: str) -> Invoice:
    text = clean_ocr(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    first = next((l for l in lines if not re.fullmatch(r"(TAX )?INVOICE", l, re.I)), None)
    eu = bool(re.search(r"\d,\d{2}\s?€", text))
    g = lambda rx: (m.group(1).strip() if (m := rx.search(text)) else None)
    totals = {k: parse_amount(g(rx)) for k, rx in TOTALS.items()}
    items, in_table = [], False
    for l in lines:
        if HEADER_ROW.match(l):
            in_table = True
            continue
        if in_table and STOP_ROW.match(l):
            break
        if in_table and (m := LINE.match(l)):
            unit, amount = parse_amount(m.group(3)), parse_amount(m.group(4))
            if unit is None or amount is None:
                continue  # unreadable row: dropping it breaks the subtotal check, which sends the doc to review
            items.append(LineItem(description=m.group(1), quantity=m.group(2), unit_price=unit, amount=amount))
    return Invoice(
        invoice_number=g(NUMBER), vendor_name=first,
        invoice_date=parse_date(g(ISSUED), dayfirst=eu), due_date=parse_date(g(DUE), dayfirst=eu),
        currency=detect_currency(text),
        subtotal=totals["subtotal"], discount=abs(totals["discount"]) if totals["discount"] is not None else 0,
        tax=totals["tax"], total=totals["total"], line_items=items,
    )
