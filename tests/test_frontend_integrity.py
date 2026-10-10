"""Regression checks for UI element wiring and visible discovery styles.

These guard against screen cleanup accidentally deleting live JS dependencies.
"""
import re
from pathlib import Path
import web_dashboard

def test_all_direct_dom_lookups_have_matching_html_ids():
    page = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    lookups = set(re.findall(r'E\(["\']([^"\']+)["\']\)', page))
    rendered = set(re.findall(r'\bid="([^"]+)"', page))
    assert not (lookups - rendered), sorted(lookups - rendered)

def test_web_discovery_has_branded_tabs_and_real_run_handling():
    page = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    assert ".rfp-tabs{" in page
    assert ".rfp-tabs button.active{" in page
    assert ".rfp-kpi{" in page
    assert "function showRunError(message)" in page
    assert "function showRunEmptyState()" in page
    assert "Unable to load intelligence data" in page
    assert "No saved intelligence runs found" in page
    assert 'data-page="overview"' in page

def test_removed_components_are_not_written_to():
    page = Path(web_dashboard.WEB).read_text(encoding="utf-8")
    for deleted in ("breadcrumb", "health", "pipeline"):
        assert f"E('{deleted}')" not in page
        assert f'E("{deleted}")' not in page
    assert 'id="view-workflow"' not in page
