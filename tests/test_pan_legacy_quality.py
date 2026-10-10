import json
from web_dashboard import run_detail


def test_legacy_pan_records_are_not_all_sales_opportunities(tmp_path):
    topic = "PAN"
    records = [
        {"title": None, "tender_reference": None, "issuing_authority": "IT Department",
         "scope_summary": "General unrelated department circular about pan-India policy",
         "document_url": "https://example.gov.in/notices/notice1.pdf",
         "document_sha256": "unrelated"},
        {"title": None, "tender_reference": None, "issuing_authority": "IT Department",
         "scope_summary": "PAN verification systems",
         "document_url": "https://example.gov.in/notices/notice2.pdf",
         "document_sha256": "incomplete"},
        {"title": "RFP for PAN Card Verification Services",
         "tender_reference": "PAN-2026-001", "issuing_authority": "IT Department",
         "scope_summary": "The agency shall develop a PAN verification API integration for the department portal.",
         "document_url": "https://example.gov.in/notices/notice3.pdf",
         "document_sha256": "valid"},
    ]
    (tmp_path / "opportunities.json").write_text(json.dumps({
        "topic": topic, "run_id": "20261010T120000000000Z",
        "steps": {"analysis": {"documents_analyzed": 3}},
        "opportunities": records
    }), encoding="utf-8")
    documents = [
        {"sha256": "unrelated", "document_url": records[0]["document_url"],
         "text": "Government circular on pan-India office policy. Tender not issued."},
        {"sha256": "incomplete", "document_url": records[1]["document_url"],
         "text": "Request for Proposal PAN card verification API services."},
        {"sha256": "valid", "document_url": records[2]["document_url"],
         "text": "Tender request for PAN card verification API services. The agency shall provide integration support."},
    ]
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    result = run_detail(tmp_path)
    assert len(result["opportunities"]) == 1
    assert result["opportunities"][0]["tender_reference"] == "PAN-2026-001"
    assert result["qualification_summary"]["needs_review"] == 1
    assert result["qualification_summary"]["excluded"] == 1
    assert len(result["documents"]) == 3
