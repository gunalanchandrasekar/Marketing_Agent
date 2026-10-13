from github_web_intelligence import normalize_hit, queries_for_web, search_web
import web_dashboard
from fastapi.testclient import TestClient


def test_github_web_queries_cover_repositories_issues_discussions():
    queries = queries_for_web("DigiLocker")
    assert len(queries) == 8
    assert all("site:github.com" in q for q in queries)
    assert any(q.endswith('"DigiLocker"') for q in queries)
    assert any("issues" in q for q in queries)
    assert any("discussions" in q for q in queries)


def test_web_result_types_and_non_github_urls():
    cases = {
        "https://github.com/org/digilocker-sdk": "repository",
        "https://github.com/org/portal/issues/42": "issue",
        "https://github.com/org/portal/discussions/12": "discussion",
        "https://github.com/org/portal/blob/main/digilocker.md": "web_reference",
    }
    for url, expected in cases.items():
        row = normalize_hit({"href": url, "title": "DigiLocker OAuth API", "body": "Integration"})
        assert row is not None
        assert row["kind"] == expected
    assert normalize_hit({"href": "https://untrusted.example/digilocker"}) is None


def test_independent_web_search_deduplicates_and_persists(tmp_path):
    rows = [
        {"href": "https://github.com/org/digilocker-sdk", "title": "DigiLocker API SDK", "body": "Integration"},
        {"href": "https://github.com/org/digilocker-sdk", "title": "DigiLocker API SDK", "body": "Integration"},
        {"href": "https://github.com/org/portal/issues/19", "title": "Need DigiLocker integration", "body": "OAuth error"},
        {"href": "https://github.com/org/portal/discussions/22", "title": "DigiLocker integration discussion", "body": "API"},
        {"href": "https://example.com/unrelated", "title": "DigiLocker", "body": "ignore"},
    ]
    out = search_web("DigiLocker", tmp_path, max_results=10,
                     search_provider=lambda query, count: rows)
    assert out["mode"] == "web"
    assert len(out["repositories"]) == 1
    assert len(out["issues"]) == 1
    assert len(out["discussions"]) == 1
    assert out["coverage"]["queries_succeeded"] == 8
    assert out["coverage"]["raw_search_hits"] == 40
    assert out["coverage"]["duplicate_hits"] >= 3
    assert (tmp_path / out["id"] / "results.json").exists()


def test_index_failure_is_not_confirmed_zero(tmp_path):
    def fail(*args):
        raise RuntimeError("Index provider unavailable")
    result = search_web("DigiLocker", tmp_path, search_provider=fail)
    assert result["search_health"] == "unavailable"
    assert result["coverage"]["queries_succeeded"] == 0
    assert len(result["errors"]) == 8


def test_api_rejects_unknown_search_mode():
    client = TestClient(web_dashboard.app)
    response = client.post("/api/github/search", json={
        "topic": "DigiLocker", "mode": "not_supported",
    })
    assert response.status_code == 422


def test_github_two_mode_screen():
    html = web_dashboard.WEB.read_text(encoding="utf-8")
    assert 'data-gh-mode="web"' in html
    assert 'data-gh-mode="direct"' in html
    assert "function setGithubMode(mode)" in html
    assert "mode:ghMode" in html
    assert 'data-gh-tab="web_results"' in html
    assert 'data-gh-tab="all"' in html
    assert "ghTab=ghData.mode==='web'?'all':'issues'" in html


def test_search_exposes_discovery_funnel_and_keeps_other_github_pages(tmp_path):
    rows = [
        {"href": "https://github.com/surepassio/surepass-digiboost-web-sdk",
         "title": "DigiLocker web SDK for digital ID", "body": "API integration"},
        {"href": "https://github.com/ProteaneGovTechnologies/Protean-RISE-APIs/blob/main/README.md",
         "title": "Protean RISE APIs DigiLocker documentation", "body": "PAN and DigiLocker integration"},
        {"href": "https://github.com/org/portal/issues/44",
         "title": "DigiLocker API integration help", "body": "OAuth callback failing"},
        {"href": "https://non-github.test/not-github", "title": "DigiLocker", "body": "Ignore"},
        {"href": "https://github.com/org/other", "title": "Different project", "body": "Unrelated"},
    ]
    out = search_web("DigiLocker", tmp_path, max_results=10,
                     search_provider=lambda query, count: rows)
    assert len(out["repositories"]) == 1
    assert len(out["issues"]) == 1
    assert len(out["web_results"]) == 1
    assert out["coverage"]["indexed_github_urls"] == 3
    assert out["coverage"]["non_github_or_invalid"] == 8
    assert out["coverage"]["topic_unmatched"] == 8
    assert out["coverage"]["duplicate_hits"] >= 15
