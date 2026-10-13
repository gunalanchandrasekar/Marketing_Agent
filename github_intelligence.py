"""GitHub community intelligence for public repositories and issue discussions.

It identifies technical demand signals, not confirmed procurement leads. All
findings retain their original GitHub URL and explanations of why they matched.
The optional GITHUB_TOKEN environment variable raises REST API rate limits.
"""
from __future__ import annotations

import json
import base64
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

from relevance import topic_present

API = "https://api.github.com"
USER_AGENT = "VAF-Marketing-Intelligence/1.0"
MAX_RESULTS = 30
IT_TERMS = re.compile(
    r"(?i)\b(?:api|oauth|integration|sdk|software|backend|frontend|"
    r"python|java|javascript|typescript|fastapi|react|database|"
    r"microservice|authentication|webhook|portal|developer|"
    r"deployment|security|workflow|bug|feature|automation|"
    r"endpoint|implementation|connect(?:or|ion)|digital|e-?governance)\b"
)
DEMAND_TERMS = re.compile(
    r"(?i)\b(?:help|need|looking for|request|feature request|"
    r"unable|error|failing|fails|broken|issue|problem|"
    r"how (?:to|do)|support|implement|integrat(?:e|ion)|"
    r"missing|bug|fix|blocked|assistance|struggling)\b"
)
STOP = re.compile(r"[\r\n\t]+")
VALID_TOPIC = re.compile(r"^[\w .+#/-]{2,100}$", re.UNICODE)


def safe_topic(value: str) -> str:
    topic = value.strip()
    if (not VALID_TOPIC.fullmatch(topic)
            or topic.startswith(("-", "/", "."))
            or ".." in topic
            or "/" in topic
            or "\\" in topic):
        raise ValueError("Topic must be 2–100 characters and contain ordinary topic terms")
    return topic


def matches(topic: str, text: str) -> bool:
    # Leverage PAN, DigiLocker, and singular/plural checks used in tender research.
    return topic_present(topic, text)


def query_terms(topic: str) -> list[str]:
    topic = safe_topic(topic)
    terms = [f'"{topic}"']
    if re.sub(r"[\W_]", "", topic.lower()) == "digilocker":
        terms += ['"Digi Locker"', '"Digi-locker"']
    elif topic.lower() == "pan":
        terms = ['"PAN verification"', '"PAN card"', '"Permanent Account Number"']
    elif topic.lower() == "ration card":
        terms += ['"ration cards"']
    return terms[:4]


def _request(client: httpx.Client, endpoint: str, params: dict) -> dict:
    """Query public GitHub search, falling back to anonymous for token-scope errors.

    Fine-grained PATs may authenticate successfully but have insufficient
    permissions for searching issues in repositories outside their scope.
    Public search works without a PAT, subject to stricter rate limits.
    """
    response = client.get(API + endpoint, params=params)
    if response.status_code in (401, 403, 404) and client.headers.get("Authorization"):
        # Use a distinct anonymous request; never send the PAT to another host.
        safe_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        with httpx.Client(headers=safe_headers,
                          timeout=httpx.Timeout(18, connect=8),
                          follow_redirects=False) as public:
            fallback = public.get(API + endpoint, params=params)
        if fallback.is_success:
            response = fallback
            used_public_fallback = True
        else:
            used_public_fallback = False
    else:
        used_public_fallback = False
    if response.status_code in (401, 403, 429):
        remaining = response.headers.get("x-ratelimit-remaining", "unknown")
        raise RuntimeError(
            f"GitHub search unavailable (HTTP {response.status_code}). "
            f"Remaining quota: {remaining}. Verify GITHUB_TOKEN permissions, API search "
            "limits or try again later. No results were confirmed."
        )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Unexpected GitHub search response")
    if used_public_fallback:
        data["_public_fallback"] = True
    return data

def _priority(topic: str, title: str, body: str, *, kind: str) -> tuple[int, str]:
    title_match = matches(topic, title)
    body_match = matches(topic, body)
    if not (title_match or body_match):
        return 0, "No topic match in title or description"
    excerpt = (title + " " + body)[:6500]
    technical = bool(IT_TERMS.search(excerpt))
    demand = kind == "issue" and bool(DEMAND_TERMS.search(excerpt))
    points = 3 + (3 if title_match else 0) + (2 if technical else 0) + (2 if demand else 0)
    if kind == "issue" and demand and technical:
        label = "Developer help / implementation request"
    elif technical:
        label = "Relevant IT implementation or repository"
    else:
        label = "Topic mention — technical demand unverified"
    return min(10, points), label


def _readme_text(client: httpx.Client, fullname: str) -> str:
    """Read README evidence for repositories found through GitHub README search."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", fullname or ""):
        return ""
    try:
        response = client.get(API + "/repos/" + fullname + "/readme")
        if not response.is_success:
            return ""
        payload = response.json()
        encoded = payload.get("content") or ""
        if payload.get("encoding") != "base64" or len(encoded) > 160_000:
            return ""
        return base64.b64decode(encoded).decode("utf-8", "replace")[:18000]
    except (httpx.HTTPError, ValueError, TypeError):
        return ""


def _record_repo(topic: str, item: dict, readme: str = "") -> dict | None:
    title = item.get("full_name") or item.get("name") or ""
    description = item.get("description") or ""
    tags = [str(t) for t in (item.get("topics") or [])]
    score, reason = _priority(topic, " ".join([title, *tags]), description, kind="repo")
    if not score and readme and matches(topic, readme):
        score = 5 + (2 if IT_TERMS.search(readme) else 0)
        reason = "Technical topic found in repository README"
    if not score:
        return None
    return {
        "kind": "repository", "id": str(item.get("id") or ""),
        "title": title, "url": item.get("html_url"), "description": description[:1200],
        "owner": (item.get("owner") or {}).get("login"),
        "language": item.get("language"), "stars": item.get("stargazers_count") or 0,
        "forks": item.get("forks_count") or 0,
        "updated_at": item.get("updated_at"), "created_at": item.get("created_at"),
        "is_archived": bool(item.get("archived")), "score": score, "reason": reason,
        "topics": tags[:12],
        "evidence": ("README directly mentions the topic." if "README" in reason else
                     "Repository name, topics or description matched the query."),
    }


def _record_issue(topic: str, item: dict) -> dict | None:
    # GitHub issue search also returns pull requests; do not conflate them.
    if "pull_request" in item:
        return None
    title = item.get("title") or ""
    body = STOP.sub(" ", item.get("body") or "")[:6000]
    score, reason = _priority(topic, title, body, kind="issue")
    if not score:
        return None
    repo_url = item.get("repository_url") or ""
    repo_name = repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else ""
    return {
        "kind": "issue", "id": str(item.get("id") or ""),
        "title": title, "url": item.get("html_url"), "description": body[:1200],
        "repository": repo_name, "number": item.get("number"),
        "state": item.get("state"), "comments": item.get("comments") or 0,
        "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
        "score": score, "reason": reason,
        "evidence": "Issue title or body contains matching source terms.",
    }


DISCUSSIONS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    discussions(first: 20, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {title bodyText url createdAt updatedAt comments {totalCount}}
    }
  }
}
"""


def _fetch_discussions(client: httpx.Client, topic: str, repository: str) -> list[dict]:
    """Fetch relevant public GitHub Discussions for a known matching repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
        return []
    owner, name = repository.split("/", 1)
    response = client.post(API + "/graphql", json={
        "query": DISCUSSIONS_QUERY, "variables": {"owner": owner, "name": name},
    })
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError("GraphQL discussions unavailable for " + repository + ": "
                         + str(payload["errors"][0].get("message", "Unknown error"))[:140])
    node = (payload.get("data") or {}).get("repository") or {}
    entries = ((node.get("discussions") or {}).get("nodes") or [])
    rows = []
    for entry in entries:
        title, body = entry.get("title") or "", entry.get("bodyText") or ""
        score, reason = _priority(topic, title, body, kind="issue")
        if not score:
            continue
        rows.append({
            "kind": "discussion", "title": title, "description": body[:1200],
            "url": entry.get("url"), "repository": repository,
            "state": "discussion", "comments": (entry.get("comments") or {}).get("totalCount", 0),
            "created_at": entry.get("createdAt"), "updated_at": entry.get("updatedAt"),
            "score": score, "reason": reason,
            "evidence": "Discussion title or body directly mentions the topic.",
        })
    return rows


def search_github(
    topic: str, output_root: Path, *, max_results: int = 20,
    token: str | None = None, progress=None,
) -> dict:
    topic = safe_topic(topic)
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError("max_results must be between 1 and 30")
    terms = query_terms(topic)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    data = {
        "id": timestamp, "topic": topic,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repositories": [], "issues": [], "discussions": [], "issues_found": 0,
        "repositories_found": 0, "search_queries": [], "errors": [],
        "note": "Public code and developer activity are not confirmed procurement or buyer demand. Discussions are sampled from matching repositories when token access permits.",
    }
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": USER_AGENT}
    # Dashboard startup does not automatically load .env; resolve here so the
    # GitHub token is available even when Python is launched from Git Bash.
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    secret = token or os.getenv("GITHUB_TOKEN")
    data["authentication"] = "token" if secret else "anonymous"
    if secret:
        headers["Authorization"] = "Bearer " + secret
    if progress:
        progress("github_search", "Searching public GitHub repositories and issues", 10)
    seen_repos: dict[str, dict] = {}
    seen_issues: dict[str, dict] = {}
    # GitHub's unauthenticated SEARCH quota is small. Search developer issues
    # first, then repositories, and use two focused variants per category.
    # Never confuse a failed search with a confirmed zero-match search.
    planned_terms = terms[:2]
    searches = [
        (kind, endpoint, term) for kind, endpoint in (
            ("issue", "/search/issues"),
            ("repository", "/search/repositories"),
        ) for term in planned_terms
    ]
    coverage = {
        "issue_queries_attempted": 0, "issue_queries_succeeded": 0,
        "repository_queries_attempted": 0, "repository_queries_succeeded": 0,
        "api_total_issue_matches": 0, "api_total_repository_matches": 0,
        "public_fallback_queries": 0,
    }
    with httpx.Client(headers=headers, timeout=httpx.Timeout(18, connect=8),
                      follow_redirects=False) as client:
        for index, (kind, endpoint, term) in enumerate(searches, 1):
            group = "issue" if kind == "issue" else "repository"
            coverage[group + "_queries_attempted"] += 1
            query = term + (" is:issue in:title,body" if kind == "issue"
                            else " in:name,description,readme")
            params = {"q": query, "sort": "updated", "order": "desc", "per_page": max_results}
            data["search_queries"].append({"kind": kind, "q": query})
            try:
                payload = _request(client, endpoint, params)
                coverage[group + "_queries_succeeded"] += 1
                if payload.get("_public_fallback"):
                    coverage["public_fallback_queries"] += 1
                total_count = int(payload.get("total_count") or 0)
                if kind == "issue":
                    coverage["api_total_issue_matches"] += total_count
                    data["issues_found"] += total_count
                    for raw in payload["items"]:
                        row = _record_issue(topic, raw)
                        if row and row["url"]:
                            seen_issues[row["url"]] = row
                else:
                    coverage["api_total_repository_matches"] += total_count
                    data["repositories_found"] += total_count
                    for raw in payload["items"]:
                        row = _record_repo(topic, raw)
                        if row is None and len(seen_repos) < max_results:
                            row = _record_repo(topic, raw, readme=_readme_text(
                                client, raw.get("full_name") or ""))
                        if row and row["url"]:
                            seen_repos[row["url"]] = row
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                data["errors"].append({"kind": kind, "query": query, "message": str(exc)[:320]})
            if progress:
                progress("github_search", f"Checked {index}/{len(searches)} GitHub searches",
                         15 + int(75 * index / len(searches)))
    # A failed GitHub Issues API must not suppress relevant public issue pages.
    # Recover separately through the web index, without treating those pages
    # as verified REST API issue records or changing the API success count.
    coverage["web_issue_fallback_attempted"] = False
    coverage["web_issue_fallback_saved"] = 0
    if coverage["issue_queries_succeeded"] == 0:
        coverage["web_issue_fallback_attempted"] = True
        try:
            from github_web_intelligence import search_web
            secondary = search_web(topic, output_root.parent / "github_web_fallback",
                                   max_results=max_results)
            for web_issue in secondary.get("issues", []):
                url = web_issue.get("url")
                if url and url not in seen_issues:
                    web_issue["source"] = "Indexed web search (GitHub API unavailable)"
                    web_issue["state"] = "unknown"
                    seen_issues[url] = web_issue
                    coverage["web_issue_fallback_saved"] += 1
            data["fallback_issues"] = coverage["web_issue_fallback_saved"]
            if secondary.get("search_health") != "complete":
                data["errors"].append({
                    "kind": "web_fallback",
                    "query": topic,
                    "message": "Secondary web index incomplete: " +
                               str(secondary.get("search_health")) +
                               "; " + str(len(secondary.get("errors", []))) + " query failures.",
                })
        except Exception as exc:
            data["errors"].append({
                "kind": "web_fallback", "query": topic,
                "message": type(exc).__name__ + ": " + str(exc)[:240],
            })
    data["coverage"] = coverage
    data["search_health"] = (
        "fallback" if coverage["web_issue_fallback_saved"] else
        "issues_unavailable" if coverage["issue_queries_succeeded"] == 0
        else "partial" if data["errors"] else "complete"
    )
    # Strongest evidence first; among similar hits surface recently updated,
    # non-archived projects and actively discussed open issues.
    repo_order = sorted(seen_repos.values(), key=lambda x: x.get("updated_at") or "", reverse=True)
    repo_order = sorted(repo_order, key=lambda x: (
        -x["score"], x.get("is_archived", False), -(x.get("stars") or 0)
    ))
    issue_order = sorted(seen_issues.values(), key=lambda x: x.get("updated_at") or "", reverse=True)
    issue_order = sorted(issue_order, key=lambda x: (
        -x["score"], x.get("state") != "open"
    ))
    data["repositories"] = repo_order[:max_results]
    data["discussion_health"] = "not_checked"
    # Discussions have a separate GraphQL API and may be disabled on some repos.
    # Search a bounded sample of identified topic-related repositories.
    if secret and data["repositories"]:
        discussions = {}
        targets = [row["title"] for row in data["repositories"][:5]
                   if "/" in row.get("title", "")]
        data["discussion_health"] = "partial"
        with httpx.Client(headers=headers, timeout=httpx.Timeout(18, connect=8),
                          follow_redirects=False) as discussion_client:
            succeeded = 0
            for repository in targets:
                try:
                    for row in _fetch_discussions(discussion_client, topic, repository):
                        if row.get("url"):
                            discussions[row["url"]] = row
                    succeeded += 1
                except (httpx.HTTPError, ValueError) as exc:
                    data["errors"].append({
                        "kind": "discussion", "query": repository,
                        "message": str(exc)[:260],
                    })
            data["discussions"] = sorted(discussions.values(),
                                         key=lambda x: (-x["score"], x.get("updated_at") or ""))[:max_results]
            data["discussion_health"] = ("complete" if succeeded == len(targets)
                                         else "partial" if succeeded else "unavailable")
    elif not secret:
        data["discussion_health"] = "token_required"

    data["issues"] = issue_order[:max_results]
    data["counts"] = {
        "repositories": len(data["repositories"]), "issues": len(data["issues"]),
        "discussions": len(data["discussions"]),
        "open_issues": sum(x.get("state") == "open" for x in data["issues"]),
        "developer_requests": sum(x["score"] >= 8 for x in data["issues"]),
        "errors": len(data["errors"]),
    }
    data["completed_at"] = datetime.now(timezone.utc).isoformat()
    path = output_root / timestamp
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    if progress:
        progress("complete", "GitHub community scan completed", 100)
    return data


def check_github_connection(topic: str = "DigiLocker") -> dict:
    """Test one real public issue search; never include token or response headers."""
    topic = safe_topic(topic)
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    query = query_terms(topic)[0] + " is:issue in:title,body"
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(18, connect=8),
                          follow_redirects=False) as client:
            result = _request(client, "/search/issues",
                              {"q": query, "per_page": 5})
        samples = [
            {"title": item.get("title"), "url": item.get("html_url")}
            for item in result.get("items", [])[:5] if item.get("html_url")
        ]
        return {
            "status": "ok", "topic": topic,
            "authentication": "token_configured" if token else "anonymous",
            "public_fallback_used": bool(result.get("_public_fallback")),
            "github_issue_matches": result.get("total_count", 0),
            "sample_issues": samples,
            "note": "Matches are public issue search results, not verified customer leads.",
        }
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        return {
            "status": "failed", "topic": topic,
            "authentication": "token_configured" if token else "anonymous",
            "error": str(exc)[:300], "github_issue_matches": None,
        }


def load_github_run(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"\d{8}T\d{12}Z", run_id):
        raise ValueError("Invalid GitHub scan ID")
    try:
        return json.loads((root / run_id / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("GitHub scan not found") from exc
