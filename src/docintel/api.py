"""The FastAPI + Jinja2 demo this repo declared (the `api` extra in pyproject.toml)
but never actually built. Wraps `pipeline.process()` — no new logic, just a UI on
top of the existing library so the review-queue and straight-through-rate story
is visible without reading Python.

Run: uv run --extra api uvicorn docintel.api:app --reload --app-dir src
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .pipeline import process
from .review import QueueMetrics

app = FastAPI(title="doc-intelligence-api demo")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# In-memory, single-process metrics — this is a local demo, not a deployed service.
metrics = QueueMetrics()
history: list[dict] = []

SAMPLE_DOCUMENTS = {
    "clean_invoice": """TAX INVOICE
Invoice No: INV-2026-0148
Invoice Date: 11/09/2026
Due Date: 25/09/2026
Vendor: Lahore Textiles Pvt Ltd
NTN: 1234567
STRN: 03-02-9999-123-45
Subtotal: 23,700.00
Sales Tax: 4,029.00
Total: 27,729.00
IBAN: PK36SCBL0000001123456702
""",
    "broken_total_invoice": """TAX INVOICE
Invoice No: INV-2026-0201
Invoice Date: 03/09/2026
Due Date: 18/09/2026
Vendor: Karachi Electronics Traders
NTN: 7654321
Subtotal: 12,000.00
Sales Tax: 2,040.00
Total: 27,300.00
""",
    "contract": """SERVICE AGREEMENT
Party A: Faisalabad Agro Exports
Party B: NIBGE Testing Services
Effective Date: 01/06/2026
Expiry Date: 31/05/2027
Governing Law: Islamic Republic of Pakistan
""",
    "cnic": """NATIONAL IDENTITY CARD
Name: Amina Sheikh
CNIC Number: 35202-1234567-1
Date of Birth: 14/03/1994
Date of Expiry: 14/03/2032
""",
}

SAMPLE_LINE_ITEMS = {
    "clean_invoice": [{"amount": "12000"}, {"amount": "8500"}, {"amount": "3200"}],
    "broken_total_invoice": [{"amount": "6000"}, {"amount": "6000"}],
}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "samples": SAMPLE_DOCUMENTS,
            "result": None,
            "metrics": metrics.summary(),
            "history": history,
        },
    )


@app.post("/process", response_class=HTMLResponse)
async def process_document(
    request: Request,
    text: str = Form(...),
    sample_key: str = Form(""),
) -> HTMLResponse:
    line_items = SAMPLE_LINE_ITEMS.get(sample_key)
    document = process(text, line_items=line_items)
    metrics.add(document)

    summary = document.summary()
    history.insert(0, {"document_type": summary["document_type"], **summary})
    del history[20:]  # keep the demo view bounded

    review_queue = [
        {
            "field": item.field,
            "question": item.question(),
            "critical": item.critical,
            "confidence": item.confidence,
        }
        for item in document.review_queue
    ]

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "samples": SAMPLE_DOCUMENTS,
            "submitted_text": text,
            "result": {
                "summary": summary,
                "values": document.values,
                "review_queue": review_queue,
                "auto_approved": document.auto_approved,
            },
            "metrics": metrics.summary(),
            "history": history,
        },
    )
