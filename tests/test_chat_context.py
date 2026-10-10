import json
from fastapi.testclient import TestClient
import web_dashboard
from chat_context import build_chat_context, relevant_passages

def test_chat_context_scopes_pdf(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "opportunities.json").write_text(json.dumps({"topic":"DigiLocker","opportunities":[]}))
    (run / "extracted_tenders.json").write_text(json.dumps({"documents":[{"sha256":"aa","text":"DigiLocker integration required for issuing certificates."},{"sha256":"bb","text":"Completely different agriculture scheme."}]}))
    context = build_chat_context(run, "issuing certificates", "aa")
    assert "issuing certificates" in context
    assert "agriculture" not in context

def test_unknown_pdf_rejected(tmp_path):
    import pytest
    (tmp_path / "opportunities.json").write_text("{}")
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({"documents":[]}))
    with pytest.raises(ValueError):
        build_chat_context(tmp_path, "question", "not-a-document")

def test_chat_endpoint_uses_selected_run(monkeypatch, tmp_path):
    run_id="20261009T073609740173Z"
    path=tmp_path/"digilocker"/run_id
    path.mkdir(parents=True)
    (path/"opportunities.json").write_text(json.dumps({"topic":"DigiLocker","run_id":run_id,"steps":{},"opportunities":[]}))
    (path/"extracted_tenders.json").write_text(json.dumps({"documents":[{"sha256":"abc","text":"Submission deadline 31 August 2026"}]}))
    monkeypatch.setattr(web_dashboard,"RUNS",tmp_path)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message":{"content":"The document says 31 August 2026."}}
    monkeypatch.setattr(web_dashboard.httpx,"post",lambda *a,**k: Response())
    res=TestClient(web_dashboard.app).post("/api/chat",json={"run_id":run_id,"message":"What is deadline?","model":"qwen3:30b"})
    assert res.status_code==200
    assert "31 August" in res.json()["answer"]


def test_selected_tender_context_excludes_another_tender_analysis(tmp_path):
    (tmp_path / "opportunities.json").write_text(json.dumps({
        "topic": "DigiLocker",
        "opportunities": [
            {"title":"Tender A", "document_sha256":"aa", "scope_summary":"Portal integration"},
            {"title":"Tender B", "document_sha256":"bb", "scope_summary":"Agriculture fertilizer supply"},
        ]
    }))
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({
        "documents": [
            {"sha256":"aa", "document_url":"https://test.gov.in/a.pdf",
             "text":"The agency shall integrate DigiLocker API into the citizen portal."},
            {"sha256":"bb", "document_url":"https://test.gov.in/b.pdf",
             "text":"Tender for fertilizer supply to agriculture field offices."},
        ]
    }))
    context = build_chat_context(tmp_path, "What are the technical requirements?", "aa")
    assert "DigiLocker API" in context
    assert "fertilizer" not in context.lower()
    assert "test.gov.in/b.pdf" not in context


def test_missing_readable_pdf_cannot_be_sent_to_ai(tmp_path):
    import pytest
    (tmp_path / "opportunities.json").write_text(json.dumps({"topic":"DigiLocker","opportunities":[]}))
    (tmp_path / "extracted_tenders.json").write_text(json.dumps({
        "documents":[{"sha256":"aa","document_url":"https://test.gov.in/scanned.pdf","text":""}]
    }))
    with pytest.raises(ValueError, match="No readable extracted tender text"):
        build_chat_context(tmp_path, "Summarize this tender", "aa")


def test_tender_view_chat_requires_exact_document_binding():
    from pathlib import Path
    page = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    assert "documentSha!==activeTenderSha" in page
    assert "Opened tender has no matching extracted PDF" in page
    assert "setActiveTender(o)" in page


def test_chat_selected_pdf_is_only_context_sent_to_ollama(monkeypatch, tmp_path):
    run_id = "20261010T071000000000Z"
    run = tmp_path / "digilocker" / run_id
    run.mkdir(parents=True)
    (run / "opportunities.json").write_text(json.dumps({"topic": "DigiLocker", "run_id": run_id, "opportunities": []}))
    (run / "extracted_tenders.json").write_text(json.dumps({
        "documents": [
            {"sha256": "alpha", "document_url": "https://example.gov.in/alpha.pdf",
             "text": "Tender A requires DigiLocker integration with the citizen portal."},
            {"sha256": "beta", "document_url": "https://example.gov.in/beta.pdf",
             "text": "Tender B requires purchasing agricultural tractors."},
        ],
    }))
    monkeypatch.setattr(web_dashboard, "RUNS", tmp_path)
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "DigiLocker integration is required."}}
    def fake_post(url, json, **kwargs):
        captured["request"] = json
        return Response()
    monkeypatch.setattr(web_dashboard.httpx, "post", fake_post)
    res = TestClient(web_dashboard.app).post("/api/chat", json={
        "run_id": run_id, "message": "What must we integrate?",
        "document_sha256": "alpha", "model": "qwen3:30b",
    })
    assert res.status_code == 200
    source = captured["request"]["messages"][1]["content"]
    assert "DigiLocker integration" in source
    assert "agricultural tractors" not in source
    assert res.json()["document_sha256"] == "alpha"


def test_ollama_connection_failure_has_actionable_error(monkeypatch, tmp_path):
    import httpx
    run_id = "20261010T071000000001Z"
    run = tmp_path / "digilocker" / run_id
    run.mkdir(parents=True)
    (run / "opportunities.json").write_text(json.dumps({"topic": "DigiLocker", "run_id": run_id, "opportunities": []}))
    (run / "extracted_tenders.json").write_text(json.dumps({
        "documents": [{"sha256": "alpha", "text": "RFP for DigiLocker API integration portal."}],
    }))
    monkeypatch.setattr(web_dashboard, "RUNS", tmp_path)
    def fail(url, **kwargs):
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("connection failed", request=request)
    monkeypatch.setattr(web_dashboard.httpx, "post", fail)
    res = TestClient(web_dashboard.app).post("/api/chat", json={
        "run_id": run_id, "message": "Summarize technical requirements",
        "document_sha256": "alpha", "model": "qwen3:30b",
    })
    assert res.status_code == 503
    assert "OLLAMA_BASE_URL" in res.json()["detail"]
