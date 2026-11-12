# invx: invoice extraction that knows when it doesn't know

A PDF → validated JSON pipeline for invoices, built the way a forward-deployed engineer would build it at a new customer. Its goal is not maximum accuracy on a demo set. **It reports how many documents can safely skip a human, and it never auto-approves a wrong number.**

```
PDF ──► text layer? ──yes──► rules extractor ──► validator ──ok──► auto-approve
          │ no                                      │ issues
          ▼                                         ▼
      Tesseract OCR                        optional Claude fallback (tool use, schema-forced)
                                                    │
                                              validator again ──ok──► auto-approve
                                                    │ issues
                                                    ▼
                                             human review queue (with reasons)
```

The **validator** is the core idea. Invoices carry redundancy: line amounts sum to the subtotal, subtotal − discount + tax = total, and qty × unit price = amount. A misread digit almost anywhere breaks at least one equation, so the system can tell whether to trust its own output **without any ground truth**.

## Evaluation

There is no public invoice dataset with exact labels and controllable layouts, so `invx.generate` produces them:

- **4 layouts.** They differ in labels ("Invoice No" / "Invoice #" / "Bill Number" / "Ref."), date formats (ISO, DD/MM/YYYY, "March 9, 2026", "09 Mar 2026"), number formats (`1,234.56` vs `1.234,56 €`), currencies and column order.
- **One layout is held out.** The rules were written against the other three, which simulates the first unseen vendor template.
- **40% are delivered as degraded scans**: image-only PDFs at 150 dpi, ±1.2° skew, blur, noise and JPEG artefacts, so they need OCR.
- **About 8% contain a vendor arithmetic error** (the printed total ≠ the lines). A correct pipeline must extract the wrong total *and* refuse to auto-approve it.

**Methodology:** I debugged on a dev set (seed 11), froze the code, then generated a fresh test set (seed 13, 400 invoices) and ran once. Numbers below are from that test run ([`results/eval_rules.json`](results/eval_rules.json)), rules only, with no LLM.

| Slice | Docs | Header field accuracy* | Line items exact | Fully correct | **Auto-approved** | **Precision of auto-approved** | Vendor errors auto-approved |
|---|---|---|---|---|---|---|---|
| Seen layouts, digital | 175 | 100% | 100% | 100% | 91.4% | **100%** (160/160) | 0 / 15 |
| Seen layouts, scanned | 125 | 96–100% | 60.0% | 54.4% | 48.8% | **96.7%** (59/61) | 0 / 15 |
| Held-out layout, digital | 56 | 0%** | 0% | 0% | 0% | n/a | 0 / 3 |
| Held-out layout, scanned | 44 | 0%** | 0% | 0% | 0% | n/a | 0 / 4 |

\* per field over 9 header fields. \*\* except currency (100%), which comes from the symbol.

### Reading it

- **Zero wrong numbers were auto-approved, and none of the 37 invoices with vendor arithmetic errors got through.** The two auto-approved scanned documents that weren't perfect had cosmetic OCR errors in a line description (`integration services` for `Integration services`, and a stray trailing `:`); every amount was right. That is also the validator's honest limit: **it guards numbers, not free text.**
- **On the unseen template, the rules extract nothing, and the system knows it.** All 100 held-out invoices were routed to review with explicit reasons (`missing invoice_number`, `no line items`, ...). The failure mode is "more work for a human", not "wrong data in the ERP".
- **OCR is the bottleneck on scans.** Header fields survive (96–100%), but table rows often lose a digit or a separator, which the subtotal check catches. That is why the straight-through rate falls to 49% while precision stays at 97%.
- **One improvement I tried and reverted:** median-filter plus threshold preprocessing before OCR *lowered* fully-correct scans from 49% to 19% on the dev set. Tesseract's own binarisation does better, so the raw render goes to OCR.

### The LLM fallback, and what's not measured

When the rules output fails validation, `process(text, llm=extract_llm)` sends the text to Claude with a **forced tool call** whose input schema is the pydantic `Invoice` model, then validates the answer with the same equations. The fallback replaces the rules output only if it has fewer validation issues. If the LLM call errors, the document goes to review instead of being lost. This is the cascade I'd use in production: cheap deterministic rules for the 90% of documents from known vendors, an LLM for the long tail, and arithmetic as the referee for both.

**I have not run the fallback against this test set** (no API key in the environment I built this in), so I make no accuracy claim for it. Its control flow is unit-tested with stubbed clients. Run `python -m invx.evaluate --llm` with `ANTHROPIC_API_KEY` set to measure it. The held-out rows above are the number it should move.

## Run it

```bash
brew install tesseract            # or apt-get install tesseract-ocr
uv venv && uv pip install -e '.[gen,api,llm,dev]'
python -m invx.generate --n 400 --seed 13 --out data
python -m invx.evaluate --data data          # ~80 s, OCR dominates
pytest
uvicorn invx.api:app &
curl -s -F file=@data/pdf/inv_0000.pdf localhost:8000/extract | jq '.route, .issues'
```

Docker: `docker build -t invx . && docker run -p 8000:8000 invx` (Tesseract included).

## Layout

```
src/invx/
  schema.py     pydantic Invoice / LineItem: the contract every extractor meets
  generate.py   synthetic invoices: 4 layouts, scan degradation, vendor arithmetic errors, exact truth
  parsing.py    locale-aware amounts (1.234,56 vs 1,234.56) and dates (day-first only for EU formatting)
  rules.py      regex extractor + OCR clean-up (grid lines read as |, stray quotes)
  validate.py   arithmetic and completeness checks → reasons a human can act on
  llm.py        Claude tool-use extractor (schema-forced)
  pipeline.py   text/OCR → rules → validate → optional fallback → route
  evaluate.py   field-level scoring split by seen/held-out × digital/scanned
  api.py        FastAPI POST /extract with size and type checks
```

## Limitations

- Synthetic data. Real invoices bring multi-page tables, handwriting, stamps, and vendors who omit subtotals. The generator covers layout and scan variance, not all of that.
- Single-page invoices only in the generator. The pipeline reads all pages, but multi-page tables are untested.
- The validator can't catch a wrong invoice number or vendor name. A production deployment would match those against the customer's vendor master and open purchase orders.
