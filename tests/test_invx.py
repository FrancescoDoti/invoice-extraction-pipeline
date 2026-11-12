import random
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from faker import Faker

from invx.generate import make_truth, render
from invx.parsing import parse_amount, parse_date
from invx.pipeline import pdf_text, process
from invx.rules import extract_rules
from invx.schema import Invoice, LineItem
from invx.validate import validate


@pytest.mark.parametrize("text,expected", [
    ("1.234,56 €", "1234.56"), ("$1,234.56", "1234.56"), ("£0.00", "0.00"), ("-911,93 €", "-911.93"), ("12", "12"), ("€", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == (Decimal(expected) if expected else None)


def test_parse_date_respects_day_first():
    assert parse_date("03/04/2026", dayfirst=True) == date(2026, 4, 3)
    assert parse_date("March 9, 2026", dayfirst=False) == date(2026, 3, 9)
    assert parse_date("not a date", dayfirst=False) is None


def good_invoice(**kw) -> Invoice:
    base = dict(invoice_number="1", invoice_date=date(2026, 1, 1), vendor_name="V", currency="EUR",
                subtotal=Decimal("30.00"), tax=Decimal("6.00"), total=Decimal("36.00"),
                line_items=[LineItem(description="a", quantity=Decimal(3), unit_price=Decimal("10.00"), amount=Decimal("30.00"))])
    return Invoice(**{**base, **kw})


def test_validator_accepts_consistent_and_flags_each_break():
    assert validate(good_invoice()) == []
    assert "subtotal - discount + tax != total" in validate(good_invoice(total=Decimal("37.00")))
    assert "missing invoice_number" in validate(good_invoice(invoice_number=None))
    assert "due date before invoice date" in validate(good_invoice(due_date=date(2025, 1, 1)))
    bad = good_invoice(line_items=[LineItem(description="a", quantity=Decimal(3), unit_price=Decimal("10.00"), amount=Decimal("31.00"))])
    assert {"line 1: qty x unit price != amount", "line items do not sum to subtotal"} <= set(validate(bad))


def test_rules_skip_unreadable_rows_instead_of_crashing():
    text = "INVOICE\nAcme\nInvoice No: 7\nDescription Qty Unit Price Amount\nWidget 2 10.00 -\nSubtotal 20.00\n"
    inv = extract_rules(text)
    assert inv.line_items == [] and inv.subtotal == Decimal("20.00")


@pytest.mark.parametrize("layout", ["classic", "european", "modern"])
def test_digital_round_trip_for_seen_layouts(tmp_path, layout):
    rng, fake = random.Random(5), Faker()
    for _ in range(3):
        t = make_truth(rng, fake, layout)
        path = tmp_path / "x.pdf"
        render(t, path, fake)
        text, ocr = pdf_text(path)
        r = process(text)
        assert not ocr
        assert str(r.invoice.total) == t["total"] and r.invoice.invoice_number == t["invoice_number"]
        assert r.route == ("auto_approve" if t["arithmetic_ok"] else "human_review")


def test_unknown_layout_goes_to_review_not_auto_approve(tmp_path):
    rng, fake = random.Random(1), Faker()
    t = make_truth(rng, fake, "compact")
    render(t, tmp_path / "c.pdf", fake)
    assert process(pdf_text(tmp_path / "c.pdf")[0]).route == "human_review"


def test_llm_fallback_used_only_when_it_validates_better():
    good = good_invoice()
    r = process("garbage text", llm=lambda text: good)
    assert r.route == "auto_approve" and r.stages == ["rules", "llm"]

    def boom(text):
        raise TimeoutError
    r = process("garbage text", llm=boom)
    assert r.route == "human_review" and any("llm fallback failed" in i for i in r.issues)


def test_llm_extractor_forces_tool_call():
    from invx.llm import extract_llm
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=good_invoice().model_dump(mode="json"))])
    inv = extract_llm("text", client=SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert seen["tool_choice"] == {"type": "tool", "name": "record_invoice"}
    assert inv.total == Decimal("36.00")


def test_api(tmp_path):
    from fastapi.testclient import TestClient
    from invx.api import app
    rng, fake = random.Random(2), Faker()
    t = make_truth(rng, fake, "classic")
    render(t, tmp_path / "a.pdf", fake)
    c = TestClient(app)
    r = c.post("/extract", files={"file": ("a.pdf", (tmp_path / "a.pdf").read_bytes(), "application/pdf")})
    assert r.status_code == 200 and r.json()["invoice"]["total"] == t["total"]
    assert c.post("/extract", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 415
