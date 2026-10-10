"""Document-grounded context construction for the VAF tender chatbot.

Only reads files belonging to the selected run. Long documents are searched for
question-relevant passages rather than sending just the first pages.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

def read(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}

def relevant_passages(text: str, question: str, limit: int = 15000) -> str:
    if not text:
        return ""
    tokens = set(re.findall(r"[a-z0-9]{3,}", question.lower())) - {
        "the", "what", "which", "that", "this", "tell", "about", "with", "from",
        "please", "document", "tender", "have", "does", "summarize"
    }
    chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
    scored = sorted(enumerate(chunks), key=lambda row: (
        -sum(row[1].lower().count(token) for token in tokens), row[0]
    ))
    selected = [row for row in scored[:max(1, limit // 1800)]]
    selected.sort(key=lambda row: row[0])
    # Include start of document for summary and title even when relevant passages occur later.
    lead = text[:2500]
    rest = "\n\n".join(f"[CHARACTER OFFSET {i*1800}]\n{chunk}" for i, chunk in selected)
    return (lead + "\n\n" + rest)[:limit]

def build_chat_context(run_dir: Path, question: str, document_sha256: str | None = None) -> str:
    run = read(run_dir / "opportunities.json")
    extracted = read(run_dir / "extracted_tenders.json")
    docs = extracted.get("documents") or []
    if document_sha256:
        docs = [d for d in docs if d.get("sha256") == document_sha256]
        if not docs:
            raise ValueError("Document does not belong to selected run")
    if not any((d.get("text") or "").strip() for d in docs):
        raise ValueError("No readable extracted tender text is available for the selected document. Check the Documents page.")
    parts = [f"TOPIC: {run.get('topic', '')}"]
    if document_sha256:
        parts.append("DOCUMENT SCOPE: Only the explicitly selected tender document is permitted.")
    permitted = {d.get("sha256") for d in docs}
    for item in run.get("opportunities") or []:
        if document_sha256 and item.get("document_sha256") not in permitted:
            continue
        facts = {k: item.get(k) for k in (
            "title", "tender_reference", "issuing_authority", "publication_date",
            "submission_deadline", "deadline_status", "scope_summary",
            "technical_requirements", "eligibility_requirements", "why_relevant_to_topic",
            "verification_status", "document_url"
        )}
        parts.append("EXTRACTED ANALYSIS (provisional): " + json.dumps(facts, ensure_ascii=False))
    # Allocate a finite per-document passage budget across the available PDFs.
    allowance = max(3000, min(15000, 30000 // max(len(docs), 1)))
    for index, doc in enumerate(docs, 1):
        parts.append(f"DOCUMENT {index}: {doc.get('document_url', '')}\n"
                     + relevant_passages(doc.get("text") or "", question, allowance))
    return "\n\n".join(parts)[:43000]
