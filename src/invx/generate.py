"""Synthetic invoice PDFs with exact ground truth.

Four layouts differ in labels, date and number formats, currency style and table
column order. Layout "compact" is held out: the rule-based extractor was written
against the other three, so its score there measures generalisation to an unseen
vendor template, the situation an FDE meets on day one at a new customer.

About 8% of invoices carry a vendor arithmetic error (the printed total does not
match the lines). Ground truth records what is printed plus `arithmetic_ok`, so the
validator can be scored on catching them.

python -m invx.generate --n 400 --out data
"""
import argparse
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LAYOUTS = ["classic", "european", "modern", "compact"]
HELD_OUT = {"compact"}
CURRENCY = {"classic": "USD", "european": "EUR", "modern": "USD", "compact": "GBP"}
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}
ITEMS = ["Consulting hours", "Cloud hosting (monthly)", "Data labelling batch", "Software licence", "On-site workshop",
         "GPU compute hours", "Support retainer", "API usage tier", "Security audit", "Model fine-tuning job",
         "Travel expenses", "Hardware rental", "Training session", "Integration services", "Annual maintenance"]
CENT = Decimal("0.01")


def q(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def money(x: Decimal, layout: str) -> str:
    s = f"{x:,.2f}"
    if layout == "european":
        return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"
    if layout == "compact":
        return "£" + s
    if layout == "modern":
        return "$" + s
    return s


def fmt_date(d: date, layout: str) -> str:
    return {"classic": d.isoformat(), "european": d.strftime("%d/%m/%Y"),
            "modern": d.strftime("%B %d, %Y").replace(" 0", " "), "compact": d.strftime("%d %b %Y")}[layout]


def make_truth(rng: random.Random, fake: Faker, layout: str) -> dict:
    items = []
    for desc in rng.sample(ITEMS, rng.randint(1, 7)):
        qty = Decimal(rng.choice([1, 1, 2, 3, 4, 5, 8, 10, 12, 20, 40]))
        unit = q(rng.choice([rng.uniform(5, 200), rng.uniform(200, 4000)]))
        items.append({"description": desc, "quantity": str(qty), "unit_price": str(unit), "amount": str(q(qty * unit))})
    subtotal = q(sum(Decimal(i["amount"]) for i in items))
    discount = q(subtotal * Decimal(rng.choice([5, 10]))) / 100 if rng.random() < 0.25 else Decimal("0.00")
    discount = q(discount)
    rate = Decimal(rng.choice([0, 5, 10, 20, 22]))
    tax = q((subtotal - discount) * rate / 100)
    total = subtotal - discount + tax
    arithmetic_ok = True
    if rng.random() < 0.08:  # vendor typo in the printed total
        total += q(rng.choice([-1, 1]) * rng.choice([Decimal("0.10"), Decimal("1.00"), Decimal("10.00"), Decimal("90.00")]))
        arithmetic_ok = False
    issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    return {
        "invoice_number": rng.choice(["INV-", "", "A", "2026/"]) + str(rng.randint(1000, 99999)),
        "invoice_date": issued.isoformat(),
        "due_date": (issued + timedelta(days=rng.choice([14, 30, 45, 60]))).isoformat(),
        "vendor_name": fake.company(),
        "currency": CURRENCY[layout],
        "subtotal": str(subtotal), "discount": str(discount), "tax": str(tax), "total": str(q(total)),
        "tax_rate": str(rate), "line_items": items, "layout": layout, "arithmetic_ok": arithmetic_ok,
    }


def render(t: dict, path: Path, fake: Faker) -> None:
    L = t["layout"]
    st = getSampleStyleSheet()
    D = date.fromisoformat
    m = lambda k: money(Decimal(t[k]), L)
    story = []
    buyer = fake.company()
    if L == "classic":
        story += [Paragraph("INVOICE", st["Title"]), Paragraph(t["vendor_name"], st["Heading2"]),
                  Paragraph(f"Invoice No: {t['invoice_number']}", st["Normal"]),
                  Paragraph(f"Date: {fmt_date(D(t['invoice_date']), L)}", st["Normal"]),
                  Paragraph(f"Due Date: {fmt_date(D(t['due_date']), L)}", st["Normal"]),
                  Paragraph(f"Bill To: {buyer}", st["Normal"]), Paragraph("All amounts in USD", st["Normal"]), Spacer(1, 12)]
        head = ["Description", "Qty", "Unit Price", "Amount"]
        rows = [[i["description"], i["quantity"], money(Decimal(i["unit_price"]), L), money(Decimal(i["amount"]), L)] for i in t["line_items"]]
        totals = [["Subtotal", m("subtotal")]] + ([["Discount", "-" + m("discount")]] if Decimal(t["discount"]) else []) + \
                 [[f"VAT ({t['tax_rate']}%)", m("tax")], ["Total", m("total")]]
    elif L == "european":
        story += [Paragraph(t["vendor_name"], st["Title"]), Paragraph(f"Invoice # {t['invoice_number']}", st["Heading2"]),
                  Paragraph(f"Issue date: {fmt_date(D(t['invoice_date']), L)}", st["Normal"]),
                  Paragraph(f"Payment due: {fmt_date(D(t['due_date']), L)}", st["Normal"]),
                  Paragraph(f"Customer: {buyer}", st["Normal"]), Spacer(1, 12)]
        head = ["Item", "Quantity", "Price", "Total"]
        rows = [[i["description"], i["quantity"], money(Decimal(i["unit_price"]), L), money(Decimal(i["amount"]), L)] for i in t["line_items"]]
        totals = [["Net amount", m("subtotal")]] + ([["Discount", "-" + m("discount")]] if Decimal(t["discount"]) else []) + \
                 [[f"Tax {t['tax_rate']}%", m("tax")], ["Amount due", m("total")]]
    elif L == "modern":
        story += [Paragraph(f"<para align=right>{t['vendor_name']}</para>", st["Heading2"]),
                  Paragraph(f"Bill Number {t['invoice_number']}", st["Heading1"]),
                  Paragraph(f"Issued {fmt_date(D(t['invoice_date']), L)} · Due {fmt_date(D(t['due_date']), L)}", st["Normal"]),
                  Paragraph(f"Billed to {buyer}", st["Normal"]), Spacer(1, 12)]
        head = ["Service", "Units", "Rate", "Line total"]
        rows = [[i["description"], i["quantity"], money(Decimal(i["unit_price"]), L), money(Decimal(i["amount"]), L)] for i in t["line_items"]]
        totals = [["Subtotal", m("subtotal")]] + ([["Discount", "-" + m("discount")]] if Decimal(t["discount"]) else []) + \
                 [[f"Tax ({t['tax_rate']}%)", m("tax")], ["Grand Total", m("total")]]
    else:  # compact, held out: different labels, quantity-first columns
        story += [Paragraph(f"{t['vendor_name']} — TAX INVOICE", st["Heading2"]),
                  Paragraph(f"Ref. {t['invoice_number']} | Dated {fmt_date(D(t['invoice_date']), L)} | Pay by {fmt_date(D(t['due_date']), L)}", st["Normal"]),
                  Paragraph(f"For: {buyer}", st["Normal"]), Spacer(1, 8)]
        head = ["Qty", "Item", "Each", "Net"]
        rows = [[i["quantity"], i["description"], money(Decimal(i["unit_price"]), L), money(Decimal(i["amount"]), L)] for i in t["line_items"]]
        totals = [["Net total", m("subtotal")]] + ([["Less discount", m("discount")]] if Decimal(t["discount"]) else []) + \
                 [[f"Sales tax @ {t['tax_rate']}%", m("tax")], ["TOTAL DUE", m("total")]]
    table = Table([head] + rows, colWidths=[230, 60, 90, 90] if L != "compact" else [50, 240, 90, 90])
    style = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (1, 1), (-1, -1), "RIGHT")]
    if L in ("classic", "european"):
        style.append(("GRID", (0, 0), (-1, -1), 0.4, colors.grey))
    table.setStyle(TableStyle(style))
    tt = Table(totals, colWidths=[380, 90])
    tt.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    story += [table, Spacer(1, 10), tt]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def degrade_to_scan(path: Path, rng: random.Random) -> None:
    """Replace a digital PDF with an image-only 'scan': 150 dpi, slight skew, blur, noise, JPEG artefacts."""
    import io

    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    page = pdfium.PdfDocument(str(path))[0]
    img = page.render(scale=150 / 72).to_pil().convert("L")
    img = img.rotate(rng.uniform(-1.2, 1.2), expand=True, fillcolor=255, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    arr = np.asarray(img, dtype=np.int16) + np.random.default_rng(rng.randint(0, 2**31)).normal(0, rng.uniform(4, 14), img.size[::-1]).astype(np.int16)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(35, 70))
    Image.open(buf).save(path, "PDF", resolution=150)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="data")
    ap.add_argument("--scan-rate", type=float, default=0.4, help="share of invoices delivered as degraded scans")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    fake = Faker()
    Faker.seed(a.seed)
    out = Path(a.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    truths = []
    for k in range(a.n):
        layout = LAYOUTS[k % len(LAYOUTS)]
        t = make_truth(rng, fake, layout)
        t["file"] = f"inv_{k:04d}.pdf"
        render(t, out / "pdf" / t["file"], fake)
        t["scanned"] = rng.random() < a.scan_rate
        if t["scanned"]:
            degrade_to_scan(out / "pdf" / t["file"], rng)
        truths.append(t)
    (out / "truth.jsonl").write_text("\n".join(json.dumps(t) for t in truths) + "\n")
    print(f"wrote {a.n} invoices to {out}")


if __name__ == "__main__":
    main()
