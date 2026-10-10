"""Normalized, explainable discovery signals for each Marketing Agent run.

This is a conservative triage layer, NOT AI lead scoring or bid verification.
Every saved candidate is retained, including rejected and uninspected sources.
"""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROCUREMENT = re.compile(r"\b(tender|rfp|rfe|rfq|eoi|bid|bidding|procurement|empanel(?:ment|led)?|expression of interest|request for proposal|request for quotation)\b", re.I)
REFERENCE = re.compile(r"\b(api specification|developer guide|user manual|documentation|api reference|swagger|tutorial|how to|sop)\b", re.I)
AWARD = re.compile(r"\b(awarded|award notice|selected agencies|agencies selected|letter of award|contract winner)\b", re.I)
TRACKING = re.compile(r"^(utm_[^=]*|fbclid|gclid|ref|source)$", re.I)

def canonical(url: str | None) -> str:
    """Canonical URL used only for exact-source dedup, never project merging."""
    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return ""
        host = parts.hostname.lower().rstrip(".")
        port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        if path != "/":
            path = path.rstrip("/")
        params = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                        if not TRACKING.match(k))
        return urlunsplit((parts.scheme.lower(), host + port, path, urlencode(params), ""))
    except ValueError:
        return ""

def official_domain(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
        return host in ("gov.in", "nic.in") or host.endswith((".gov.in", ".nic.in"))
    except ValueError:
        return False

def normalize(topic: str, discovery: dict, extracted: dict | None = None,
              analyses: dict | None = None) -> dict:
    extracted = extracted or {}
    analyses = analyses or {}
    created = datetime.now(timezone.utc).isoformat()
    pages = {canonical(p.get("url")): p for p in discovery.get("pages", []) if canonical(p.get("url"))}
    docs = {canonical(d.get("document_url") or d.get("url")): d
            for d in discovery.get("documents", []) if canonical(d.get("document_url") or d.get("url"))}
    parsed = {canonical(d.get("document_url")): d
              for d in extracted.get("documents", []) if canonical(d.get("document_url"))}
    analyzed = {canonical(a.get("document_url")): a.get("analysis") or {}
                for a in analyses.get("results", []) if canonical(a.get("document_url"))}
    saved_candidates = discovery.get("candidates")
    if saved_candidates is None:
        saved_candidates = [{"url": p.get("url"), "search_queries": p.get("search_queries", [])}
                            for p in discovery.get("pages", [])]
    inputs = [(x, "web_candidate") for x in saved_candidates]
    inputs += [({"url": p.get("url"), "title": p.get("title"), "search_queries": p.get("search_queries", [])}, "inspected_page")
               for p in discovery.get("pages", [])]
    inputs += [({"url": d.get("document_url") or d.get("url")}, "downloaded_document")
               for d in discovery.get("documents", [])]
    signals: dict[str, dict] = {}
    duplicate_events = 0
    for item, origin in inputs:
        raw_url = item.get("url")
        url = canonical(raw_url)
        if not url:
            continue
        if url in signals:
            duplicate_events += 1
            row = signals[url]
            row["origins"] = sorted(set(row["origins"] + [origin]))
            row["search_queries"] = sorted(set(row["search_queries"] + list(item.get("search_queries") or [])))
            continue
        page = pages.get(url) or {}
        doc = docs.get(url) or {}
        content = parsed.get(url) or {}
        facts = analyzed.get(url) or {}
        title = page.get("title") or item.get("title") or facts.get("tender_title") or ""
        query_text = " ".join(item.get("search_queries") or [])
        # A topic match only in the search query is not evidence that the URL/page is relevant.
        topic_present = topic.lower() in (" ".join([url, title, page.get("text") or ""])).lower()
        procurement = bool(PROCUREMENT.search(" ".join([url, title, page.get("text") or ""])[:12000]))
        if not page and not doc and not content and not facts:
            status, reason = "needs_review", "Search candidate has not been inspected; relevance and procurement status are unverified."
        elif facts:
            status, reason = "accepted", "Structured AI analysis exists; original tender facts still require official verification."
        elif doc or content:
            status, reason = "accepted", "Tender document downloaded; AI qualification may be pending."
        elif not topic_present:
            status, reason = "rejected", "Inspected page does not mention the search topic."
        elif REFERENCE.search(title) and not procurement:
            status, reason = "rejected", "Appears to be reference or API documentation rather than procurement."
        elif AWARD.search(title):
            status, reason = "needs_review", "Award/selection notice may be useful for SI tracking, not a current bid."
        elif procurement:
            status, reason = "accepted", "Inspected page contains topic and procurement terminology; document confirmation required."
        else:
            status, reason = "needs_review", "Topic appears in inspected page but procurement intent is not established."
        row = {
            "signal_id": hashlib.sha256(url.encode()).hexdigest()[:20],
            "topic": topic, "source_url": raw_url, "canonical_url": url,
            "source_type": "official_government_domain" if official_domain(url) else "other_public_web",
            "title": title or url, "issuing_authority": facts.get("issuing_authority"),
            "tender_reference": facts.get("tender_reference"),
            "signal_category": "tender_analysis" if facts else ("procurement_document" if doc or content else "web_signal"),
            "relevance_status": status, "reason": reason, "duplicate_of": None,
            "document_url": raw_url if doc or content else None,
            "submission_deadline": facts.get("submission_deadline"),
            "verification_status": "requires_official_source_check",
            "search_queries": sorted(set(item.get("search_queries") or page.get("search_queries") or [])),
            "origins": [origin],
            "processing_status": "analyzed" if facts else ("downloaded" if doc or content else "inspected" if page else "discovered"),
            "discovered_at": discovery.get("started_at") or created,
            "evidence": {"page_url": page.get("url"), "document_sha256": content.get("sha256") or doc.get("sha256")},
        }
        signals[url] = row
    rows = list(signals.values())
    counts = Counter(s["relevance_status"] for s in rows)
    return {
        "schema_version": 1, "topic": topic, "generated_at": created,
        "coverage": "all_saved_candidates" if "candidates" in discovery else "legacy_partial_candidates",
        "total": len(rows), "duplicate_events": duplicate_events,
        "counts": {k: counts.get(k, 0) for k in ("accepted", "needs_review", "rejected")},
        "signals": rows,
        "note": "This is deterministic prequalification, not VAF lead scoring or verified tender availability.",
    }

def generate(run_dir: Path) -> dict:
    def read(name: str) -> dict:
        try:
            return json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    summary = read("opportunities.json")
    discovery = read("results.json")
    extracted = read("extracted_tenders.json")
    analyzed = read("tender_analysis_retry.json")
    if not analyzed.get("results"):
        analyzed = read("tender_analysis.json")
    result = normalize(summary.get("topic") or discovery.get("topic") or "", discovery, extracted, analyzed)
    (run_dir / "signals.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
