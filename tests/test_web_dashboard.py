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
