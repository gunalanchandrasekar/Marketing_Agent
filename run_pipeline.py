"""Run search -> download -> text extraction -> Ollama analysis in one command.

Example:
    python run_pipeline.py --topic DigiLocker --model qwen3:30b
Results are provisional; official tender notices/corrigenda require verification.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from scraper import run as scrape
from extract_tenders import extract
from analyze_tenders import analyze
from cppp_adapter import discover_public_listings

load_dotenv()
LOG = logging.getLogger("marketing_agent.pipeline")


def safe_topic(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:64] or "topic"


def execute(
    topic: str,
    output_root: Path,
    *,
    model: str,
    ollama_url: str,
    max_pages: int = 40,
    max_documents: int = 10,
    per_query: int = 8,
    delay: float = 0.8,
    max_document_mb: int = 20,
    timeout: int = 600,
    searxng: str | None = None,
    cppp: bool = True,
    progress=None,
) -> dict:
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = output_root / safe_topic(topic) / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    raw = run_dir / "results.json"
    extracted = run_dir / "extracted_tenders.json"
    analyzed = run_dir / "tender_analysis.json"
    consolidated = run_dir / "opportunities.json"
    official_listings = run_dir / "cppp_public_listings.json"

    def report(stage, message, percent):
        if progress is not None:
            progress(stage, message, percent)
    report('starting', 'Preparing sources', 2)
    state: dict = {
        "topic": topic, "run_id": run_stamp, "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model, "steps": {}, "issues": [],
        "paths": {"discovery": str(raw), "extraction": str(extracted), "analysis": str(analyzed)},
    }
    if cppp:
        report('official_sources', 'Checking public procurement listings', 8)
        try:
            listings = discover_public_listings(topic)
            official_listings.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
            state["steps"]["cppp_public_listings"] = {"matches": len(listings["matches"]), "sources_checked": len(listings["sources"])}
            state["issues"].extend(listings["issues"])
            state["paths"]["cppp_public_listings"] = str(official_listings)
            state["public_listing_candidates"] = listings["matches"]
            state["coverage_note"] = listings["coverage_note"]
        except Exception as exc:
            state["issues"].append({"stage": "cppp_public_listings", "error": str(exc)})
    report('searching', 'Searching websites and downloading documents', 20)
    try:
        discovered = scrape(
            topic, searxng, raw, max_pages, max_documents, per_query, delay, max_document_mb,
            progress=report
        )
        state["steps"]["discovery"] = {
            "unique_candidates": discovered["unique_candidates"],
            "pages_fetched": discovered["pages_fetched"],
            "documents_downloaded": discovered["documents_downloaded"],
            "coverage": discovered.get("coverage", {}),
            "eligible_document_candidates": discovered.get("eligible_document_candidates", 0),
        }
        state["issues"].extend(discovered.get("errors", []))
    except Exception as exc:
        state["issues"].append({"stage": "discovery", "error": str(exc)})
        discovered = {"documents": []}

    if not discovered.get("documents"):
        state["issues"].append({
            "stage": "discovery",
            "error": "No accessible tender PDFs were downloaded. Review search coverage, page links and portal errors; this is NOT evidence that no tender exists.",
        })
    report('extracting', 'Extracting PDF text', 55)
    try:
        # Extractor reads paths relative to the current working directory.
        if not raw.exists():
            raw.write_text(json.dumps({"topic": topic, "documents": []}), encoding="utf-8")
        extracted_result = extract(raw, extracted)
        state["steps"]["extraction"] = {
            "documents_extracted": len(extracted_result.get("documents", []))
        }
        state["issues"].extend({**e, "stage": "extraction"} for e in extracted_result.get("errors", []))
    except Exception as exc:
        state["issues"].append({"stage": "extraction", "error": str(exc)})
        extracted_result = {"documents": []}

    report('analyzing', 'Analyzing tender text using Ollama', 72)
    try:
        if not extracted.exists():
            extracted.write_text(json.dumps({"topic": topic, "documents": []}), encoding="utf-8")
        analysis_result = analyze(extracted, analyzed, model, ollama_url, timeout)
        state["steps"]["analysis"] = {"documents_analyzed": len(analysis_result.get("results", []))}
        state["issues"].extend({**e, "stage": "analysis"} for e in analysis_result.get("errors", []))
    except Exception as exc:
        state["issues"].append({"stage": "analysis", "error": str(exc)})
        analysis_result = {"results": []}

    opportunities = []
    seen: set[str] = set()
    for row in analysis_result.get("results", []):
        facts = row.get("analysis", {})
        key = str(facts.get("tender_reference") or row.get("sha256") or row.get("document_url")).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        opportunities.append({
            "topic": topic,
            "title": facts.get("tender_title"),
            "tender_reference": facts.get("tender_reference"),
            "issuing_authority": facts.get("issuing_authority"),
            "opportunity_type": facts.get("opportunity_type"),
            "publication_date": facts.get("publication_date"),
            "submission_deadline": facts.get("submission_deadline"),
            "deadline_status": facts.get("deadline_status"),
            "scope_summary": facts.get("scope_summary"),
            "technical_requirements": facts.get("technical_requirements", []),
            "technical_requirements_source": facts.get("technical_requirements_source", "ai_extracted_unverified"),
            "eligibility_requirements": facts.get("eligibility_requirements", []),
            "why_relevant_to_topic": facts.get("why_relevant_to_topic"),
            "document_url": row.get("document_url"),
            "document_sha256": row.get("sha256"),
            "evidence_validation": facts.get("evidence_validation"),
            "verification_status": "requires_official_source_and_corrigenda_check",
        })

    report('saving', 'Saving results', 97)
    state["opportunities"] = opportunities
    state["opportunity_count"] = len(opportunities)
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    state["paths"]["consolidated"] = str(consolidated)
    consolidated.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    LOG.info("Completed: %s opportunities, %s issues. %s", len(opportunities), len(state["issues"]), consolidated)
    extracted_count = state.get("steps", {}).get("extraction", {}).get("documents_extracted", 0)
    analyzed_count = state.get("steps", {}).get("analysis", {}).get("documents_analyzed", 0)
    if not state.get("steps", {}).get("discovery", {}).get("documents_downloaded", 0):
        state["run_status"] = "needs_attention"
        state["run_message"] = "No accessible tender documents downloaded; inspect coverage and download diagnostics."
        report("needs_attention", state["run_message"], 100)
    elif extracted_count > analyzed_count:
        state["run_status"] = "needs_attention"
        state["run_message"] = f"{extracted_count - analyzed_count} extracted document(s) still require AI analysis."
        report("needs_attention", state["run_message"], 100)
    else:
        state["run_status"] = "complete"
        state["run_message"] = "All extracted documents processed."
        report("complete", "Finished", 100)
    consolidated.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def main() -> None:
    p = argparse.ArgumentParser(description="Marketing Agent end-to-end pipeline")
    p.add_argument("--topic", required=True)
    p.add_argument("--output-root", type=Path, default=Path("data/runs"))
    p.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3:30b"))
    p.add_argument("--ollama", default=os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434"))
    p.add_argument("--searxng", default=os.getenv("SEARXNG_URL") or None)
    p.add_argument("--no-cppp", action="store_true", help="Skip the official public-listing adapter")
    p.add_argument("--max-pages", type=int, default=40)
    p.add_argument("--max-documents", type=int, default=10)
    p.add_argument("--per-query", type=int, default=8)
    p.add_argument("--delay", type=float, default=0.8)
    p.add_argument("--max-document-mb", type=int, default=20)
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()
    if min(args.max_pages, args.max_documents, args.per_query, args.max_document_mb, args.timeout) < 1:
        p.error("All numeric limits except delay must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = execute(
        args.topic, args.output_root, model=args.model, ollama_url=args.ollama,
        searxng=args.searxng, max_pages=args.max_pages,
        max_documents=args.max_documents, per_query=args.per_query,
        delay=args.delay, max_document_mb=args.max_document_mb, timeout=args.timeout,
        cppp=not args.no_cppp
    )
    print(f"Found {result['opportunity_count']} analyzed opportunities; "
          f"{len(result['issues'])} reported issues")
    print(f"Consolidated output: {result['paths']['consolidated']}")


if __name__ == "__main__":
    main()
