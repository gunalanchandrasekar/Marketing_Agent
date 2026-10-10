import json
from pathlib import Path
from pypdf import PdfWriter
from fastapi.testclient import TestClient
import web_dashboard
from document_review import find_document, page_evidence


def setup_run(tmp_path):
    run_id = "20261010T112233123456Z"
    run = tmp_path / "data" / "runs" / "digilocker" / run_id
    docs = run / "documents"
    docs.mkdir(parents=True)
    filename = docs / ("a" * 64 + ".pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with filename.open("wb") as file:
        writer.write(file)
    record = {
        "sha256": "a" * 64,
        "local_path": str(filename),
        "document_url": "https://example.gov.in/tender.pdf",
        "page_count": 1, "text_characters": 0,
        "extraction_status": "no_embedded_text_ocr_needed", "text": "",
    }
    (run / "extracted_tenders.json").write_text(json.dumps({"documents": [record]}))
    (run / "opportunities.json").write_text(json.dumps({
        "topic": "DigiLocker", "run_id": run_id, "opportunities": [], "steps": {}
    }))
    return run_id, run, record


def test_only_pdf_from_selected_run_is_allowed(tmp_path):
    run_id, folder, row = setup_run(tmp_path)
    result = find_document(folder, "a" * 64, [row])
    assert result["path"].is_file()
    assert result["path"].parent == folder / "documents"


def test_unrelated_file_path_is_rejected(tmp_path):
    run_id, folder, row = setup_run(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-fake")
    row["local_path"] = str(outside)
    import pytest
    with pytest.raises(ValueError, match="outside selected run"):
        find_document(folder, "a" * 64, [row])


def test_pdf_preview_and_page_evidence_api(monkeypatch, tmp_path):
    run_id, folder, row = setup_run(tmp_path)
    monkeypatch.setattr(web_dashboard, "RUNS", tmp_path / "data" / "runs")
    client = TestClient(web_dashboard.app)
    pdf = client.get(f"/api/runs/{run_id}/documents/{'a'*64}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    pages = client.get(f"/api/runs/{run_id}/documents/{'a'*64}/pages",
                       params={"question": "technical requirements"})
    assert pages.status_code == 200
    assert pages.json()["pages"] == []
    not_found = client.get(f"/api/runs/{run_id}/documents/{'b'*64}/pdf")
    assert not_found.status_code == 404


def test_page_evidence_returns_true_page_numbers(monkeypatch, tmp_path):
    import document_review
    class Page:
        def __init__(self, text):
            self.text = text
        def extract_text(self):
            return self.text
    class Reader:
        def __init__(self, path, strict=False):
            self.pages = [
                Page("Cover page"),
                Page("Scope: the agency must integrate DigiLocker API services."),
                Page("Eligibility for bidders: annual turnover required."),
            ]
    monkeypatch.setattr(document_review, "PdfReader", Reader)
    hits = page_evidence(Path("sample.pdf"), "DigiLocker integration", limit=2)
    assert hits[0]["page"] == 2
    assert "integrate DigiLocker" in hits[0]["excerpt"]
