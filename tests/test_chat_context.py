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
