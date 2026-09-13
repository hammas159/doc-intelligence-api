"""Smoke tests for the FastAPI + Jinja2 demo (the `api` extra)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from docintel.api import SAMPLE_DOCUMENTS, app  # noqa: E402

client = TestClient(app)


def test_index_loads():
    response = client.get("/")
    assert response.status_code == 200
    assert "doc-intelligence-api" in response.text


def test_clean_invoice_auto_approves():
    response = client.post(
        "/process",
        data={"text": SAMPLE_DOCUMENTS["clean_invoice"], "sample_key": "clean_invoice"},
    )
    assert response.status_code == 200
    assert "straight-through" in response.text


def test_broken_total_invoice_is_flagged():
    response = client.post(
        "/process",
        data={
            "text": SAMPLE_DOCUMENTS["broken_total_invoice"],
            "sample_key": "broken_total_invoice",
        },
    )
    assert response.status_code == 200
    assert "need review" in response.text or "total" in response.text.lower()


def test_contract_sample_processes():
    response = client.post(
        "/process", data={"text": SAMPLE_DOCUMENTS["contract"], "sample_key": "contract"}
    )
    assert response.status_code == 200
