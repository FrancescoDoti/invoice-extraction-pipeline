"""POST a PDF, get validated JSON plus a routing decision.

uvicorn invx.api:app   (set ANTHROPIC_API_KEY and INVX_LLM_FALLBACK=1 to enable the Claude fallback)
"""
import os
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile

from .pipeline import pdf_text, process

app = FastAPI(title="invoice extraction")
MAX_BYTES = 10 * 1024 * 1024


def _llm():
    if os.environ.get("INVX_LLM_FALLBACK") == "1" and os.environ.get("ANTHROPIC_API_KEY"):
        from .llm import extract_llm
        return extract_llm
    return None


@app.post("/extract")
async def extract(file: UploadFile):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file larger than 10 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "expected a PDF")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        try:
            text, ocr = pdf_text(f.name)
        except Exception:
            raise HTTPException(422, "could not read this PDF")
    r = process(text, llm=_llm())
    return {"invoice": r.invoice.model_dump(mode="json"), "route": r.route, "issues": r.issues, "stages": r.stages, "ocr": ocr}


@app.get("/health")
def health():
    return {"ok": True}
