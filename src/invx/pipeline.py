"""PDF -> text -> rules -> validate -> (optional LLM fallback) -> validate -> route."""
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from .rules import extract_rules
from .schema import Invoice
from .validate import validate


@dataclass
class Result:
    invoice: Invoice
    issues: list[str]
    route: str                  # "auto_approve" or "human_review"
    stages: list[str] = field(default_factory=list)


def pdf_text(path: str | Path) -> tuple[str, bool]:
    """Text layer if the PDF has one; otherwise OCR at 300 dpi. Returns (text, used_ocr)."""
    with pdfplumber.open(path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if text.strip():
            return text, False
        import pytesseract
        # psm 6 = one uniform block: keeps table rows on one line, which the line parser needs.
        return "\n".join(pytesseract.image_to_string(p.to_image(resolution=300).original, config="--psm 6") for p in pdf.pages), True

# Tried: median filter + global threshold before OCR. It cut fully-correct scans from 49% to 19% on the
# dev set (Tesseract binarises better itself), so the raw render goes to OCR.

def process(text: str, llm=None) -> Result:
    """llm: optional callable text -> Invoice, used only when the rules output fails validation."""
    inv = extract_rules(text)
    issues = validate(inv)
    stages = ["rules"]
    if issues and llm is not None:
        try:
            cand = llm(text)
        except Exception as exc:  # an LLM outage must not lose the document; it goes to a human
            issues = issues + [f"llm fallback failed: {type(exc).__name__}"]
        else:
            cand_issues = validate(cand)
            stages.append("llm")
            if len(cand_issues) < len(issues):
                inv, issues = cand, cand_issues
    return Result(inv, issues, "auto_approve" if not issues else "human_review", stages)
