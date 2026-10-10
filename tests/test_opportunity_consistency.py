from pathlib import Path
import web_dashboard


def test_opportunity_screen_shows_qualification_not_only_ai_count():
    html = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    assert 'id="opportunity-review"' in html
    assert 'No qualified tender opportunities in this run' in html
    assert 'Analysis & qualification audit' in html
    assert 'qualified tender candidates' in html
    assert "current?.review_records" in html
    assert "current?.excluded_records" in html


def test_overview_and_opportunities_use_same_run_candidates():
    html = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    assert "E('recent-records').innerHTML=ops.length" in html
    assert "const ops=current?.opportunities||[];" in html
    assert "E('record-count').textContent=ops.length+' qualified candidates'" in html
