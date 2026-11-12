"""Business-rule validation: decides whether an extraction can skip human review.

These checks need no ground truth. They use the redundancy every invoice carries
(lines sum to the subtotal, subtotal - discount + tax = total, qty x price = amount),
so a wrong read of almost any number breaks at least one equation.
"""
from decimal import Decimal

from .schema import Invoice

TOL = Decimal("0.01")
REQUIRED = ["invoice_number", "invoice_date", "vendor_name", "currency", "subtotal", "tax", "total"]


def validate(inv: Invoice) -> list[str]:
    issues = [f"missing {f}" for f in REQUIRED if getattr(inv, f) in (None, "")]
    if not inv.line_items:
        issues.append("no line items")
    for i, li in enumerate(inv.line_items):
        if abs(li.quantity * li.unit_price - li.amount) > TOL:
            issues.append(f"line {i + 1}: qty x unit price != amount")
    if inv.subtotal is not None and inv.line_items and abs(sum(li.amount for li in inv.line_items) - inv.subtotal) > TOL:
        issues.append("line items do not sum to subtotal")
    if None not in (inv.subtotal, inv.tax, inv.total) and abs(inv.subtotal - inv.discount + inv.tax - inv.total) > TOL:
        issues.append("subtotal - discount + tax != total")
    if inv.invoice_date and inv.due_date and inv.due_date < inv.invoice_date:
        issues.append("due date before invoice date")
    return issues
