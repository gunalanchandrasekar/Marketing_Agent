import json

from technical_requirements import extract_technical_requirements
from web_dashboard import run_detail


def sample_document():
    return """INVITATION FOR BIDS
Department of Information Technology
Introduction
The department seeks an implementing agency.
Scope of Work
The selected agency shall develop an online citizen service portal with authentication.
The vendor must integrate DigiLocker APIs for document retrieval and consent flows.
The solution shall provide role-based access to the application database.
Eligibility
The bidder must have audited turnover records.
General conditions
Payment will be made within the tender terms.
"""


def test_recovers_only_literal_source_technical_requirements():
    rows = extract_technical_requirements(sample_document())
    assert any("integrate DigiLocker APIs" in row for row in rows)
    assert any("citizen service portal" in row for row in rows)
    assert not any("audited turnover" in row for row in rows)
    assert not any("RAG" in row or "LLM" in row for row in rows)


def test_does_not_invent_from_missing_document():
    assert extract_technical_requirements("") == []
    assert extract_technical_requirements("Deadline is 20 October. Evaluation in November.") == []


def test_existing_run_uses_pdf_text_without_reanalysis(tmp_path):
    run = {
        "topic": "DigiLocker",
        "run_id": "20261010T120000000000Z",
        "opportunities": [{
            "title": "RFP for DigiLocker Citizen Portal Integration",
            "scope_summary": "Develop a citizen services portal with DigiLocker API integration, authentication and document retrieval.",
            "tender_reference": "DIT-PORTAL-2026-01",
            "document_sha256": "sample-hash",
            "document_url": "https://government.example/portal.pdf",
            "technical_requirements": [],
        }],
        "steps": {},
    }
    (tmp_path / "opportunities.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({
        "documents": [{
            "sha256": "sample-hash",
            "document_url": "https://government.example/portal.pdf",
            "text": sample_document(),
            "extraction_status": "ok",
        }],
    }), encoding="utf-8")
    details = run_detail(tmp_path)
    opp = details["opportunities"][0]
    assert opp["technical_requirements_source"] == "verbatim_document_fallback"
    assert any("integrate DigiLocker" in row for row in opp["technical_requirements"])

def test_incomplete_run_is_preserved_for_review(tmp_path):
    run = {
        "topic": "DigiLocker",
        "run_id": "20261010T120000000001Z",
        "opportunities": [{
            "title": "Citizen portal RFP",
            "document_sha256": "sample-hash",
            "document_url": "https://government.example/portal.pdf",
            "technical_requirements": [],
        }],
        "steps": {},
    }
    (tmp_path / "opportunities.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({
        "documents": [{
            "sha256": "sample-hash",
            "document_url": "https://government.example/portal.pdf",
            "text": sample_document(),
            "extraction_status": "ok",
        }],
    }), encoding="utf-8")
    details = run_detail(tmp_path)
    assert details["opportunities"] == []
    assert details["qualification_summary"]["needs_review"] == 1
    assert details["review_records"][0]["reason"] == "Tender scope not sufficiently extracted"
    assert len(details["documents"]) == 1
