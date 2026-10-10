"""Recovery of timed-out Ollama analysis without rescanning or redownloading.

python retry_analysis.py --run-dir data/runs/digilocker/<run_id> --timeout 1200
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from analyze_tenders import analyze

def consolidate(state: dict, analysis: dict) -> dict:
    old = {x.get("document_sha256") or x.get("document_url"): x
           for x in state.get("opportunities", [])}
    for row in analysis.get("results", []):
        facts = row.get("analysis") or {}
        key = row.get("sha256") or row.get("document_url")
        old[key] = {
            "topic": state.get("topic"),
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
            "emd_requirements": facts.get("emd_requirements"),
            "bid_validity": facts.get("bid_validity"),
            "rate_card_acceptance": facts.get("rate_card_acceptance"),
            "why_relevant_to_topic": facts.get("why_relevant_to_topic"),
            "document_url": row.get("document_url"),
            "document_sha256": row.get("sha256"),
            "evidence_validation": facts.get("evidence_validation"),
            "verification_status": "requires_official_source_and_corrigenda_check",
        }
    state["opportunities"] = list(old.values())
    state["opportunity_count"] = len(old)
    state.setdefault("steps", {})["analysis"] = {"documents_analyzed": len(analysis.get("results", []))}
    # Retain only unresolved analysis errors; historical search/download issues stay visible.
    analyzed_urls = {x.get("document_url") for x in analysis.get("results", [])}
    state["issues"] = [
        x for x in state.get("issues", [])
        if not (x.get("stage") == "analysis" and x.get("document_url") in analyzed_urls)
    ]
    state["issues"].extend({**x, "stage": "analysis"} for x in analysis.get("errors", []))
    state["last_analysis_retry_at"] = datetime.now(timezone.utc).isoformat()
    return state

def retry(run_dir: Path, model: str, url: str, timeout: int) -> dict:
    run_dir = run_dir.resolve()
    source = run_dir / "extracted_tenders.json"
    output = run_dir / "tender_analysis_retry.json"
    consolidated = run_dir / "opportunities.json"
    if not source.is_file() or not consolidated.is_file():
        raise FileNotFoundError("Select a run with extracted_tenders.json and opportunities.json")
    state = json.loads(consolidated.read_text(encoding="utf-8"))
    previous = json.loads(source.read_text(encoding="utf-8"))
    completed = {r.get("document_sha256") for r in state.get("opportunities", [])}
    pending = [d for d in previous.get("documents", [])
               if d.get("sha256") not in completed and d.get("extraction_status") == "ok"]
    if not pending:
        return state
    temporary = run_dir / "_retry_pending.json"
    temporary.write_text(json.dumps({"topic": state.get("topic"), "documents": pending}, ensure_ascii=False), encoding="utf-8")
    try:
        result = analyze(temporary, output, model, url, timeout)
    finally:
        temporary.unlink(missing_ok=True)
    state = consolidate(state, result)
    tmp = run_dir / "opportunities.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(consolidated)
    return state

def main():
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3:30b"))
    p.add_argument("--ollama", default=os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434"))
    p.add_argument("--timeout", type=int, default=1200)
    args = p.parse_args()
    state = retry(args.run_dir, args.model, args.ollama, args.timeout)
    print(f"Recovered results: {state['opportunity_count']} opportunities, {len(state.get('issues', []))} remaining issues")

if __name__ == "__main__":
    main()
