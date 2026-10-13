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
    """Diversified discovery: broad topic coverage before specialist facets.

    Over-constrained queries like "API SDK repository" miss most discussions
    and source repositories. Restrict hosts but not every possible intent.
    """
    variants = query_terms(topic)
    main = variants[0]
    focused = variants[1] if len(variants) > 1 else main
    return [
        f"site:github.com {main}",
        f"site:github.com {main} integration",
        f"site:github.com {main} API OAuth",
        f"site:github.com {main} SDK",
        f"site:github.com {main} issues",
        f"site:github.com {main} bug feature request",
        f"site:github.com {main} discussions",
        f"site:github.com {focused} developer implementation",
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
    elif len(parts) == 2 and parts[0].lower() == "orgs":
        kind = "community"
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
    raw_hits = 0
    non_github = 0
    topic_unmatched = 0
    duplicated = 0
    search_yield = []
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
                accepted_here = 0
                for raw in hits:
                    raw_hits += 1
                    row = normalize_hit(raw)
                    if row is None:
                        non_github += 1
                        continue
                    evidence = " ".join((row["url"], row["title"], row["description"]))
                    if not matches(topic, evidence):
                        topic_unmatched += 1
                        continue
                    score, reason = _priority(topic, row["title"], evidence,
                                              kind="issue" if row["kind"] in ("issue", "discussion") else "repo")
                    row.update(score=score, reason=reason)
                    if score:
                        if row["url"] in seen:
                            duplicated += 1
                        else:
                            accepted_here += 1
                        if row["url"] not in seen or seen[row["url"]]["score"] < score:
                            seen[row["url"]] = row
                search_yield.append({"query": query, "unique_new": accepted_here})
            except Exception as exc:
                result["errors"].append({"kind": "web", "query": query,
                                         "message": f"{type(exc).__name__}: {str(exc)[:230]}"})
    for row in sorted(seen.values(), key=lambda x: -x["score"]):
        key = {"repository": "repositories", "issue": "issues",
               "discussion": "discussions"}.get(row["kind"], "web_results")
        if len(result[key]) < max_results:
            result[key].append(row)
    result["coverage"] = {
        "queries_attempted": len(queries), "queries_succeeded": succeeded,
        "indexed_github_urls": len(seen), "raw_search_hits": raw_hits,
        "non_github_or_invalid": non_github, "topic_unmatched": topic_unmatched,
        "duplicate_hits": duplicated, "query_yield": search_yield,
        "result_limit_per_category": max_results,
    }
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
