import json
from web_dashboard import run_detail

def test_run_detail_exposes_saved_discovery_urls(tmp_path):
    (tmp_path / "opportunities.json").write_text(json.dumps({"topic":"DigiLocker","opportunities":[],"steps":{}}))
    (tmp_path / "results.json").write_text(json.dumps({
        "candidates":[{"url":"https://eprocure.gov.in/tender","priority":9,"search_queries":["DigiLocker tender"]}],
        "pages":[{"url":"https://eprocure.gov.in/tender","title":"Tender notice","classification":"procurement","document_links":[]}],
        "documents":[],"errors":[]
    }))
    response=run_detail(tmp_path)
    assert response["discovery_details"]["candidate_urls_saved"] is True
    assert len(response["discovery_details"]["candidates"]) == 1
    assert response["discovery_details"]["pages"][0]["title"] == "Tender notice"

def test_legacy_runs_show_partial_candidate_coverage(tmp_path):
    (tmp_path / "opportunities.json").write_text(json.dumps({"topic":"DigiLocker","opportunities":[],"steps":{}}))
    (tmp_path / "results.json").write_text(json.dumps({"pages":[{"url":"https://example.com","title":"Notice"}]}))
    response=run_detail(tmp_path)
    assert response["discovery_details"]["candidate_urls_saved"] is False
    assert response["discovery_details"]["candidates"] == []
