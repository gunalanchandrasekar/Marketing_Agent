"""GitHub community intelligence for public repositories and issue discussions.

It identifies technical demand signals, not confirmed procurement leads. All
findings retain their original GitHub URL and explanations of why they matched.
The optional GITHUB_TOKEN environment variable raises REST API rate limits.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

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
    if not VALID_TOPIC.fullmatch(topic) or topic.startswith(("-", "/")):
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
    response = client.get(API + endpoint, params=params)
    if response.status_code in (403, 429):
        reset = response.headers.get("x-ratelimit-reset", "")
        remaining = response.headers.get("x-ratelimit-remaining", "")
        raise RuntimeError(
            "GitHub API rate limit or access restriction (HTTP "
            + str(response.status_code) + "). Remaining=" + remaining
            + ", reset=" + reset + ". Configure GITHUB_TOKEN for higher limits."
        )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("Unexpected GitHub search response")
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


def _record_repo(topic: str, item: dict) -> dict | None:
    title = item.get("full_name") or item.get("name") or ""
    description = item.get("description") or ""
    tags = [str(t) for t in (item.get("topics") or [])]
    score, reason = _priority(topic, " ".join([title, *tags]), description, kind="repo")
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
        "evidence": "Repository name, topics or description matched the query.",
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
        "repositories": [], "issues": [], "issues_found": 0,
        "repositories_found": 0, "search_queries": [], "errors": [],
        "note": "Developer activity signals, not verified RFPs or purchase intent. GitHub Discussions and private content are not indexed by these REST searches.",
    }
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": USER_AGENT}
    secret = token or os.getenv("GITHUB_TOKEN")
    if secret:
        headers["Authorization"] = "Bearer " + secret
    if progress:
        progress("github_search", "Searching public GitHub repositories and issues", 10)
    seen_repos: dict[str, dict] = {}
    seen_issues: dict[str, dict] = {}
    with httpx.Client(headers=headers, timeout=httpx.Timeout(18, connect=8),
                      follow_redirects=False) as client:
        for n, term in enumerate(terms):
            for kind, endpoint in (("repository", "/search/repositories"),
                                   ("issue", "/search/issues")):
                query = term + (" in:name,description,readme" if kind == "repository"
                                else " is:issue in:title,body")
                params = {"q": query, "sort": "updated", "order": "desc", "per_page": max_results}
                data["search_queries"].append({"kind": kind, "q": query})
                try:
                    payload = _request(client, endpoint, params)
                    if kind == "repository":
                        data["repositories_found"] += payload.get("total_count", 0)
                        for raw in payload["items"]:
                            row = _record_repo(topic, raw)
                            if row and row["url"]:
                                seen_repos[row["url"]] = row
                    else:
                        data["issues_found"] += payload.get("total_count", 0)
                        for raw in payload["items"]:
                            row = _record_issue(topic, raw)
                            if row and row["url"]:
                                seen_issues[row["url"]] = row
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    data["errors"].append({"kind": kind, "query": query, "message": str(exc)[:320]})
                if progress:
                    done = n * 2 + (1 if kind == "repository" else 2)
                    progress("github_search", f"Checked {done}/{len(terms)*2} GitHub searches",
                             15 + int(75 * done / (len(terms)*2)))
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
    data["issues"] = issue_order[:max_results]
    data["counts"] = {
        "repositories": len(data["repositories"]), "issues": len(data["issues"]),
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


def load_github_run(root: Path, run_id: str) -> dict:
    if not re.fullmatch(r"\d{8}T\d{12}Z", run_id):
        raise ValueError("Invalid GitHub scan ID")
    try:
        return json.loads((root / run_id / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("GitHub scan not found") from exc
