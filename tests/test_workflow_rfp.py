from pathlib import Path
import web_dashboard

def test_workflow_rfp_workspace_routes_to_saved_run_records(tmp_path):
    import json
    run = tmp_path / "run"
    run.mkdir()
    (run / "opportunities.json").write_text(json.dumps({
        "topic":"DigiLocker","run_id":"20261010T080000000000Z",
        "opportunities":[{"title":"DigiLocker integration RFP","document_url":"https://example.gov.in/notice.pdf"}],
        "steps":{"discovery":{"unique_candidates":2,"pages_fetched":1}}
    }))
    (run / "results.json").write_text(json.dumps({
        "candidates":[
            {"url":"https://eprocure.gov.in/eprocure/app","search_queries":["DigiLocker tender"],"priority":9},
            {"url":"https://example.org/notice","search_queries":["DigiLocker procurement"],"priority":2}
        ],
        "pages":[{"url":"https://example.org/notice","title":"Tender notice","classification":"procurement","search_queries":["DigiLocker procurement"]}],
        "documents":[{"url":"https://example.gov.in/notice.pdf"}]
    }))
    details=web_dashboard.run_detail(run)
    assert details["discovery_details"]["candidate_urls_saved"] is True
    assert len(details["discovery_details"]["candidates"])==2
    assert len(details["discovery_details"]["pages"])==1
    assert len(details["opportunities"])==1

def test_each_screen_has_a_distinct_purpose():
    page=Path(web_dashboard.WEB).read_text(encoding="utf-8")
    assert 'id="view-rfp-intelligence"' in page
    assert 'id="view-workflow"' not in page
    assert 'data-page="workflow"' not in page
    assert 'id="view-signals"' in page
    assert 'id="view-documents"' in page
    assert 'id="view-opportunities"' in page
    assert 'id="view-sources"' in page
    assert 'id="view-activity"' in page
    assert 'data-rfp-stage="documents"' not in page
    assert 'data-rfp-stage="analyses"' not in page
    assert 'data-rfp-stage="official"' not in page
    assert "openMetricDestination(" in page
    assert "renderRfpWorkspace()" in page
    assert "rfpEvidence()" in page
