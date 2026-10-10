"""Evidence-based procurement relevance and post-analysis qualification.

Do not call something a marketing opportunity just because Ollama emitted JSON.
Every exclusion is auditable; document files and raw AI results remain saved.
"""
from __future__ import annotations
import re
from typing import Any
from it_fit import it_fit

PROCUREMENT = re.compile(
    r"\b(?:tenders?|rfps?|rfqs?|reoi|eoi|rfe|procurement|bidding|bidder|"
    r"invitation to bid|request for proposals?|request for quotations?|"
    r"expression of interest|supply order|work order|nit)\b", re.I
)
TITLE_BAD = re.compile(r"(?i)^(?:untitled(?: tender)?|not (?:available|provided|specified)|n/?a|unknown|none|null|document|tender)$")
PAN_CONTEXT = re.compile(
    r"(?i)\b(?:permanent account number|pan[- ]?card|pan[- ]?verification|"
    r"pan[- ]?services?|pan[- ]?application|pan[- ]?issuance|pan[- ]?allotment|"
    r"pan[- ]?data|pan[- ]?database|pan[- ]?number|pan[- ]?integration|"
    r"income[- ]?tax.{0,25}\bpan\b)\b"
)

def topic_present(topic: str, text: str) -> bool:
    """Require meaningful terms, not substring matches such as 'pan' in 'company'."""
    topic = (topic or "").strip()
    text = text or ""
    if not topic or not text:
        return False
    normalized_topic = re.sub(r"[^a-z0-9]+", "", topic.casefold())
    if normalized_topic == "pan":
        return bool(PAN_CONTEXT.search(text))
    if normalized_topic == "digilocker":
        return bool(re.search(r"(?i)\bdigi[\s_-]*locker\b|\bdigital locker\b", text))
    terms = re.findall(r"[a-z0-9]+", topic.casefold())
    if not terms:
        return False
    # Multiple-word topic may have different whitespace/punctuation.
    expression = r"\b" + r"[\W_]*".join(map(re.escape, terms)) + r"(?:s|es)?\b"
    return bool(re.search(expression, text, re.I))

def meaningful_title(value: Any) -> bool:
    return bool(isinstance(value, str) and len(value.strip()) >= 12
                and not TITLE_BAD.fullmatch(value.strip()))

def precheck_document(topic: str, document: dict) -> tuple[bool, str]:
    """Reject clearly unrelated PDF text prior to costly AI inference."""
    text = document.get("text") or ""
    if document.get("extraction_status") != "ok" or len(text.strip()) < 100:
        return False, "No sufficiently readable embedded PDF text"
    if not topic_present(topic, text):
        return False, "Searched topic is not evidenced in PDF text"
    return True, "Document text references searched topic; pending AI procurement classification"

def qualify_analysis(topic: str, facts: dict, document: dict) -> dict:
    """Distinguish actionable candidate from off-topic / incomplete review."""
    source_text = document.get("text") or ""
    title = facts.get("tender_title")
    scope = facts.get("scope_summary") or ""
    combined = " ".join(str(x or "") for x in (
        title, scope, facts.get("why_relevant_to_topic"), source_text
    ))
    if not topic_present(topic, source_text):
        return {"status": "rejected", "reason": "No source-backed match to searched topic"}
    if not (PROCUREMENT.search(source_text) or (facts.get("tender_reference") and PROCUREMENT.search(str(title) + " " + str(scope)))):
        return {"status": "review", "reason": "No procurement/tender evidence in document"}
    if not meaningful_title(title):
        return {"status": "review", "reason": "Missing meaningful tender title; retain PDF for review"}
    if not scope or len(str(scope).strip()) < 25:
        return {"status": "review", "reason": "Tender scope not sufficiently extracted"}
    if not topic_present(topic, str(title) + " " + str(scope) + " " + source_text):
        return {"status": "rejected", "reason": "Topic appears only in unsupported AI claim"}
    fit = it_fit(title, scope, facts.get("technical_requirements") or [])
    if fit["status"] == "non_it":
        return {"status": "rejected", "reason": "Not an IT services opportunity: " + fit["reason"]}
    if fit["status"] != "it_candidate":
        return {"status": "review", "reason": "IT relevance not established: " + fit["reason"]}
    return {"status": "candidate", "reason": "Topic, tender and explicit IT service deliverables found; official status unverified"}
