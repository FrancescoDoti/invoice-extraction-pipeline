"""Field-level evaluation against ground truth, split by seen vs held-out layout.

python -m invx.evaluate --data data [--llm]
"""
import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from .generate import HELD_OUT
from .pipeline import pdf_text, process
from .schema import HEADER_FIELDS


def norm(field: str, v):
    if v is None:
        return None
    if field in ("subtotal", "discount", "tax", "total"):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    return str(v)


def items_match(pred, truth) -> bool:
    key = lambda d: (str(d["description"]), Decimal(str(d["quantity"])), Decimal(str(d["unit_price"])), Decimal(str(d["amount"])))
    return sorted(map(key, pred)) == sorted(map(key, truth))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--llm", action="store_true", help="enable the Claude fallback (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    llm = None
    if a.llm:
        from .llm import extract_llm
        llm = extract_llm
    truths = [json.loads(l) for l in open(Path(a.data) / "truth.jsonl")]
    stats = defaultdict(lambda: defaultdict(int))
    reasons = defaultdict(int)
    for t in truths:
        g = ("held_out" if t["layout"] in HELD_OUT else "seen") + ("/scanned" if t.get("scanned") else "/digital")
        text, _ = pdf_text(Path(a.data) / "pdf" / t["file"])
        r = process(text, llm=llm)
        pred = json.loads(r.invoice.model_dump_json())
        s = stats[g]
        s["docs"] += 1
        ok_fields = 0
        for f in HEADER_FIELDS:
            hit = norm(f, pred.get(f)) == norm(f, t.get(f))
            s[f"field:{f}"] += hit
            ok_fields += hit
        li = items_match(pred["line_items"], t["line_items"])
        s["line_items"] += li
        fully = ok_fields == len(HEADER_FIELDS) and li
        s["fully_correct"] += fully
        auto = r.route == "auto_approve"
        s["auto_approved"] += auto
        s["auto_approved_and_correct"] += auto and fully
        s["auto_approved_and_wrong"] += auto and not fully
        if not t["arithmetic_ok"]:
            s["vendor_errors"] += 1
            s["vendor_errors_auto_approved"] += auto
        for i in r.issues:
            reasons[i.split(":")[0] if i.startswith("line ") else i] += 1
    summary = {}
    for g, s in sorted(stats.items()):
        n = s["docs"]
        summary[g] = {
            "docs": n,
            "field_accuracy": {f: s[f"field:{f}"] / n for f in HEADER_FIELDS},
            "line_items_exact": s["line_items"] / n,
            "documents_fully_correct": s["fully_correct"] / n,
            "straight_through_rate": s["auto_approved"] / n,
            "auto_approved_precision": (s["auto_approved_and_correct"] / s["auto_approved"]) if s["auto_approved"] else None,
            "auto_approved_but_wrong": s["auto_approved_and_wrong"],
            "vendor_arithmetic_errors": s["vendor_errors"],
            "vendor_errors_auto_approved": s["vendor_errors_auto_approved"],
        }
    summary["review_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))
    summary["llm_fallback"] = a.llm
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    (out / ("eval_llm.json" if a.llm else "eval_rules.json")).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
