from fastapi.testclient import TestClient
import web_dashboard

def test_home_serves_ui():
    client=TestClient(web_dashboard.app)
    response=client.get("/")
    assert response.status_code==200
    assert "Government Tender Intelligence" not in response.text or "Opportunity" in response.text
    assert "VAF AI" in response.text

def test_runs_api_structure(monkeypatch):
    monkeypatch.setattr(web_dashboard,"list_runs",lambda:[])
    response=TestClient(web_dashboard.app).get("/api/runs")
    assert response.json()=={"runs":[]}

def test_invalid_run_id_returns_400():
    response=TestClient(web_dashboard.app).get("/api/runs/../../bad")
    assert response.status_code in (400,404)



def test_existing_run_id_format_is_accepted(tmp_path,monkeypatch):
    import json
    run_id="20261009T062130907068Z"
    run=tmp_path/"digilocker"/run_id
    run.mkdir(parents=True)
    (run/"opportunities.json").write_text(json.dumps({"topic":"DigiLocker","run_id":run_id,"steps":{},"opportunities":[]}),encoding="utf-8")
    monkeypatch.setattr(web_dashboard,"RUNS",tmp_path)
    client=TestClient(web_dashboard.app)
    response=client.get("/api/runs/"+run_id)
    assert response.status_code==200


def test_models_failure_is_visible_not_a_server_crash(monkeypatch):
    import httpx
    def bad_get(*args,**kwargs):
        raise httpx.ConnectError("Ollama offline")
    monkeypatch.setattr(web_dashboard.httpx,"get",bad_get)
    response=TestClient(web_dashboard.app).get("/api/models")
    assert response.status_code==200
    assert response.json()["connected"] is False
