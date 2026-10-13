import json

import httpx
from fastapi.testclient import TestClient

import github_intelligence as gi
import web_dashboard


def test_topic_variations_avoid_bare_pan_acronym():
    assert gi.query_terms("PAN") == [
        '"PAN verification"', '"PAN card"', '"Permanent Account Number"'
    ]
    assert gi.matches("DigiLocker", "Digi Locker API OAuth integration")
    assert not gi.matches("PAN", "PAN India furniture supplier")
    assert gi.matches("PAN", "How to implement PAN verification API?")


def test_repo_record_requires_evidence():
    base = {"id": 8, "full_name": "alice/digilocker-python",
            "description": "DigiLocker requester API integration in Python",
            "topics": ["digilocker", "api"], "owner": {"login": "alice"},
            "html_url": "https://github.com/alice/digilocker-python",
            "stargazers_count": 4, "forks_count": 2}
    result = gi._record_repo("DigiLocker", base)
    assert result["kind"] == "repository"
    assert result["url"] == base["html_url"]
    assert result["score"] >= 6
    assert gi._record_repo("Ration Card", base) is None


def test_github_issue_is_demand_signal_not_a_tender():
    issue = {"id": 41, "title": "Need help integrating DigiLocker OAuth",
             "body": "Our app fails with API callback error; looking for a fix.",
             "state": "open", "comments": 3, "number": 17,
             "html_url": "https://github.com/acme/citizen/issues/17",
             "repository_url": "https://api.github.com/repos/acme/citizen"}
    row = gi._record_issue("DigiLocker", issue)
    assert row["kind"] == "issue"
    assert row["state"] == "open"
    assert row["score"] >= 8
    assert "procurement" not in row["reason"].lower()
    assert gi._record_issue("DigiLocker", {**issue, "pull_request": {}}) is None


def test_github_search_saves_deduplicated_results(monkeypatch, tmp_path):
    repo = {"id": 8, "full_name": "alice/digilocker-python",
            "description": "DigiLocker API integration in Python",
            "topics": ["digilocker"], "owner": {"login": "alice"},
            "html_url": "https://github.com/alice/digilocker-python"}
    issue = {"id": 41, "title": "DigiLocker API integration error",
             "body": "Need help fixing OAuth integration", "state": "open",
             "html_url": "https://github.com/acme/citizen/issues/17"}
    calls = []
    def fake_request(client, endpoint, params):
        calls.append(endpoint)
        return {"total_count": 1,
                "items": [repo] if endpoint.endswith("repositories") else [issue]}
    monkeypatch.setattr(gi, "_request", fake_request)
    monkeypatch.setattr(gi, "_fetch_discussions", lambda client, topic, repo: [])
    result = gi.search_github("DigiLocker", tmp_path, max_results=10, token="test-token")
    assert len(result["repositories"]) == 1
    assert len(result["issues"]) == 1
    assert result["counts"]["open_issues"] == 1
    assert len(calls) == 4
    assert calls[0] == '/search/issues'
    assert result['coverage']['issue_queries_succeeded'] == 2
    assert result['search_health'] == 'complete'
    assert gi.load_github_run(tmp_path, result["id"])["topic"] == "DigiLocker"


def test_api_rate_limit_explained_to_user():
    def responder(request):
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0",
                                            "X-RateLimit-Reset": "123"})
    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        try:
            gi._request(client, "/search/issues", {"q": "DigiLocker"})
            assert False, "Expected rate limit error"
        except RuntimeError as exc:
            assert "GITHUB_TOKEN" in str(exc)


def test_github_api_history_and_invalid_id(monkeypatch, tmp_path):
    monkeypatch.setattr(web_dashboard, "BASE", tmp_path)
    run_id = "20261013T101122123456Z"
    output = tmp_path / "data" / "github_scans" / run_id
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps({
        "id": run_id, "topic": "DigiLocker", "repositories": [],
        "issues": [], "created_at": "2026-10-13T10:11:22Z"
    }), encoding="utf-8")
    client = TestClient(web_dashboard.app)
    assert client.get("/api/github/history").json()["scans"][0]["topic"] == "DigiLocker"
    assert client.get("/api/github/" + run_id).json()["id"] == run_id
    assert client.get("/api/github/not-an-id").status_code == 404
    assert client.post("/api/github/search", json={"topic": "../../etc/passwd"}).status_code == 422


def test_github_screen_and_progress_binding():
    ui = web_dashboard.WEB.read_text(encoding="utf-8")
    assert 'data-page="github"' in ui
    assert 'id="view-github"' in ui
    assert "function renderGitHubItems()" in ui
    assert "j.kind==='github_intelligence'" in ui


def test_failed_issue_search_is_not_misreported_as_zero_matches(monkeypatch, tmp_path):
    def unavailable(client, endpoint, params):
        if endpoint == "/search/issues":
            raise RuntimeError("GitHub search rate limit reached; configure GITHUB_TOKEN")
        return {"total_count": 0, "items": []}
    monkeypatch.setattr(gi, "_request", unavailable)
    monkeypatch.setattr(gi, "_fetch_discussions", lambda client, topic, repo: [])
    result = gi.search_github("DigiLocker", tmp_path, max_results=10, token="fake")
    assert result["issues"] == []
    assert result["coverage"]["issue_queries_attempted"] == 2
    assert result["coverage"]["issue_queries_succeeded"] == 0
    assert result["search_health"] == "issues_unavailable"
    assert len([x for x in result["errors"] if x["kind"] == "issue"]) == 2


def test_partial_issue_search_retains_matching_issue(monkeypatch, tmp_path):
    issue = {"id": 5, "title": "DigiLocker integration problem",
             "body": "Need help with OAuth API", "state": "open",
             "html_url": "https://github.com/acme/project/issues/5"}
    calls = {"issue": 0}
    def mixed(client, endpoint, params):
        if endpoint == "/search/issues":
            calls["issue"] += 1
            if calls["issue"] == 2:
                raise RuntimeError("API limit reached")
            return {"total_count": 269, "items": [issue]}
        return {"total_count": 0, "items": []}
    monkeypatch.setattr(gi, "_request", mixed)
    monkeypatch.setattr(gi, "_fetch_discussions", lambda client, topic, repo: [])
    result = gi.search_github("DigiLocker", tmp_path, max_results=10, token="fake")
    assert len(result["issues"]) == 1
    assert result["search_health"] == "partial"
    assert result["coverage"]["api_total_issue_matches"] == 269
    assert result["counts"]["issues"] == 1


def test_authenticated_issue_search_falls_back_to_public_without_leaking_token(monkeypatch):
    original = httpx.Client(headers={"Authorization": "Bearer private_token"},
                            transport=httpx.MockTransport(
                                lambda request: httpx.Response(
                                    403, headers={"X-RateLimit-Remaining": "10"}
                                )))
    seen = []
    class PublicClient:
        def __init__(self, headers, **kwargs):
            assert "Authorization" not in headers
            self.headers = headers
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, params):
            seen.append(url)
            return httpx.Response(200, json={"total_count": 269, "items": []},
                                  request=httpx.Request("GET", url))
    monkeypatch.setattr(gi.httpx, "Client", PublicClient)
    try:
        payload = gi._request(original, "/search/issues",
                              {"q": '"DigiLocker" is:issue'})
    finally:
        original.close()
    assert payload["_public_fallback"] is True
    assert payload["total_count"] == 269
    assert seen == ["https://api.github.com/search/issues"]

def test_readme_relevance_admits_matching_repo_without_title_match():
    raw = {
        "id": 31, "full_name": "example/digital-wallet-client",
        "description": "Credential wallet reference implementation",
        "owner": {"login": "example"},
        "html_url": "https://github.com/example/digital-wallet-client",
        "topics": ["identity"],
    }
    assert gi._record_repo("DigiLocker", raw) is None
    row = gi._record_repo("DigiLocker", raw,
                          readme="This project integrates DigiLocker OAuth API document retrieval.")
    assert row is not None
    assert row["url"] == raw["html_url"]
    assert "README" in row["reason"]


def test_github_discussions_extracted_only_when_topic_in_source(monkeypatch):
    import httpx
    payload = {"data": {"repository": {"discussions": {"nodes": [
        {"title": "DigiLocker OAuth API integration help",
         "bodyText": "How do I fetch user documents from DigiLocker?",
         "url": "https://github.com/orgs/example/discussions/32",
         "createdAt": "2026-09-01T00:00:00Z",
         "updatedAt": "2026-10-01T00:00:00Z",
         "comments": {"totalCount": 9}},
        {"title": "Unrelated topic", "bodyText": "No overlap",
         "url": "https://github.com/orgs/example/discussions/99",
         "comments": {"totalCount": 1}},
    ]}}}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        rows = gi._fetch_discussions(client, "DigiLocker", "example/digital-wallet")
    assert len(rows) == 1
    assert rows[0]["kind"] == "discussion"
    assert rows[0]["comments"] == 9


def test_github_env_token_loaded_from_dotenv(monkeypatch, tmp_path):
    from pathlib import Path
    captured = {}
    def remember(path, override=False):
        captured["path"] = str(path)
    monkeypatch.setattr(gi, "load_dotenv", remember)
    monkeypatch.setattr(gi, "_request",
                        lambda client, endpoint, params: {"total_count": 0, "items": []})
    gi.search_github("DigiLocker", tmp_path, max_results=1)
    assert captured["path"].endswith(".env")

def test_github_connection_diagnostic_returns_real_issue_count(monkeypatch):
    monkeypatch.setattr(gi, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    def fake_request(client, endpoint, params):
        assert endpoint == "/search/issues"
        assert "DigiLocker" in params["q"]
        return {"total_count": 269, "items": [{
            "title": "Implement DigiLocker connector for verified user documents",
            "html_url": "https://github.com/hushh-labs/hushh-research/issues/7829",
        }]}
    monkeypatch.setattr(gi, "_request", fake_request)
    result = gi.check_github_connection("DigiLocker")
    assert result["status"] == "ok"
    assert result["github_issue_matches"] == 269
    assert len(result["sample_issues"]) == 1
    assert "token" not in str(result).lower() or result["authentication"] == "anonymous"


def test_github_health_api_routes_are_distinct(monkeypatch):
    monkeypatch.setattr(web_dashboard, "check_github_connection",
                        lambda topic: {"status": "ok", "topic": topic,
                                       "github_issue_matches": 20})
    client = TestClient(web_dashboard.app)
    result = client.get("/api/github/health", params={"topic": "DigiLocker"})
    assert result.status_code == 200
    assert result.json()["github_issue_matches"] == 20
    assert client.get("/api/github/health", params={"topic": "../../secret"}).status_code == 422


def test_github_community_ui_and_live_connection_control():
    ui = web_dashboard.WEB.read_text(encoding="utf-8")
    assert 'data-gh-tab="discussions"' in ui
    assert 'id="gh-connection-result"' in ui
    assert "function checkGithubConnection()" in ui
