"""Independent web-index search for public GitHub code and community pages."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
import httpx
from dotenv import load_dotenv
from github_intelligence import _priority, matches, query_terms, safe_topic

LIMIT = 30

def queries_for_web(topic: str) -> list[str]:
    primary = query_terms(topic)[0]
    return [
        f"site:github.com {primary} API SDK repository",
        f"site:github.com {primary} issues integration help",
        f"site:github.com {primary} discussions developer",
        f"site:github.com {primary} implementation documentation",
    ]

def normalize_hit(item: dict) -> dict | None:
    url = item.get("href") or item.get("url") or ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("github.com", "www.github.com"):
        return None
    parts = [unquote(x) for x in parsed.path.strip("/").split("/") if x]
    if len(parts) < 2 or parts[0].lower() in {"search", "settings", "login", "topics", "features"}:
        return None
    if len(parts) > 3 and parts[2] == "issues" and parts[3].isdigit():
        kind = "issue"
    elif len(parts) > 3 and parts[2] == "discussions" and parts[3].isdigit():
        kind = "discussion"
    elif len(parts) > 3 and parts[0] == "orgs" and parts[2] == "discussions":
        kind = "discussion"
    elif len(parts) == 2:
        kind = "repository"
    else:
        kind = "web_reference"
    return {
        "kind": kind, "url": "https://github.com/" + "/".join(parts),
        "title": (item.get("title") or "").strip()[:320],
        "description": (item.get("body") or item.get("content") or "")[:1200],
        "source": "Indexed web search",
        "evidence": "Search index snippet; verify on the actual GitHub page.",
        "repository": "/".join(parts[:2]),
    }

def ddgs_search(query: str, limit: int) -> list[dict]:
    from ddgs import DDGS
    with DDGS(timeout=18) as search:
        return list(search.text(query, max_results=limit))

def searxng_search(client: httpx.Client, base: str, query: str, limit: int) -> list[dict]:
    response = client.get(base.rstrip("/") + "/search", params={
        "q": query, "format": "json", "categories": "general"})
    response.raise_for_status()
    return [{"href": x.get("url"), "title": x.get("title"), "body": x.get("content")}
            for x in response.json().get("results", [])[:limit]]

def search_web(topic: str, output_root: Path, *, max_results: int = 20,
               progress=None, search_provider=None) -> dict:
    topic = safe_topic(topic)
    if not 1 <= max_results <= LIMIT:
        raise ValueError("max_results must be between 1 and 30")
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    server = os.getenv("SEARXNG_URL", "").strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    queries = queries_for_web(topic)
    result = {
        "id": stamp, "topic": topic, "mode": "web", "created_at": datetime.now(timezone.utc).isoformat(),
        "repositories": [], "issues": [], "discussions": [], "web_results": [],
        "errors": [], "search_queries": [], "authentication": "not_required",
        "note": "Indexed GitHub web content; indexing is not complete or real-time.",
    }
    seen = {}
    succeeded = 0
    with httpx.Client(timeout=20) as client:
        for i, query in enumerate(queries, 1):
            result["search_queries"].append({"kind": "web", "q": query})
            if progress:
                progress("github_web", f"Indexed search {i}/{len(queries)}", int(10+80*i/len(queries)))
            try:
                if search_provider:
                    hits = search_provider(query, max_results)
                elif server:
                    try:
                        hits = searxng_search(client, server, query, max_results)
                    except (httpx.HTTPError, ValueError):
                        hits = ddgs_search(query, max_results)
                else:
                    hits = ddgs_search(query, max_results)
                succeeded += 1
                for raw in hits:
                    row = normalize_hit(raw)
                    if row is None:
                        continue
                    evidence = " ".join((row["url"], row["title"], row["description"]))
                    if not matches(topic, evidence):
                        continue
                    score, reason = _priority(topic, row["title"], evidence,
                                              kind="issue" if row["kind"] in ("issue", "discussion") else "repo")
                    row.update(score=score, reason=reason)
                    if score and (row["url"] not in seen or seen[row["url"]]["score"] < score):
                        seen[row["url"]] = row
            except Exception as exc:
                result["errors"].append({"kind": "web", "query": query,
                                         "message": f"{type(exc).__name__}: {str(exc)[:230]}"})
    for row in sorted(seen.values(), key=lambda x: -x["score"]):
        key = {"repository": "repositories", "issue": "issues",
               "discussion": "discussions"}.get(row["kind"], "web_results")
        if len(result[key]) < max_results:
            result[key].append(row)
    result["coverage"] = {"queries_attempted": len(queries), "queries_succeeded": succeeded,
                           "indexed_github_urls": len(seen)}
    result["search_health"] = "unavailable" if succeeded == 0 else "partial" if result["errors"] else "complete"
    result["counts"] = {
        "repositories": len(result["repositories"]), "issues": len(result["issues"]),
        "discussions": len(result["discussions"]), "web_results": len(result["web_results"]),
        "open_issues": 0, "developer_requests": sum(x["score"] >= 8 for x in result["issues"]),
        "errors": len(result["errors"]),
    }
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    path = output_root / stamp
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress:
        progress("complete", "GitHub web search finished", 100)
    return result
