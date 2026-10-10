"""Recover explicit technical deliverables from tender text without inventing requirements.

Used as a conservative fallback when the local AI omits technical requirements.
Each returned item is a literal document sentence or list line (source evidence).
"""
from __future__ import annotations

import re

HEADING = re.compile(
    r"(?i)^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(scope of work|technical requirements?|technical specifications?|"
    r"functional requirements?|functional specifications?|"
    r"system requirements?|solution requirements?|"
    r"deliverables?|implementation scope|detailed scope of work|"
    r"services required|project requirements?|technical scope)\s*[:\-–]?\s*$"
)
STOP = re.compile(
    r"(?i)^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?"
    r"(eligibility|pre.?qualification|financial bid|payment terms|"
    r"general conditions|terms and conditions|bid submission|"
    r"evaluation criteria|annexure|appendix|commercial bid|"
    r"important dates|earnest money deposit)\b"
)
TECHNICAL = re.compile(
    r"(?i)\b(?:API|integration|software|portal|application|database|"
    r"authentication|authorization|encryption|security|hosting|cloud|"
    r"mobile app|website|system|platform|interoperability|"
    r"data migration|deployment|maintenance|support|"
    r"training|testing|interface|workflow|OCR|AI|machine learning|"
    r"dashboard|payment gateway|e.?sign|DigiLocker|"
    r"personalization|printing|smart card|barcode|QR code|"
    r"biometric|infrastructure|digital signature|"
    r"functional|non.functional)\b"
)
ACTION = re.compile(
    r"(?i)\b(?:shall|must|required|provide|develop|design|implement|"
    r"integrate|configure|deploy|support|maintain|ensure|supply|"
    r"deliver|build|host|test|enable|undertake|responsible for|"
    r"provision of|installation of|development of)\b"
)
BULLET = re.compile(r"^\s*(?:[-*•]|\(?[a-zA-Z0-9]{1,3}[.)])\s*")

def extract_technical_requirements(text: str, max_items: int = 12) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    # Preserve the exact original wording for each accepted requirement.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        # Some PDF extractors flatten a page into one long line.
        lines = [part.strip() for part in re.split(r"(?<=[.;])\s+", text) if part.strip()]
    in_scope = False
    scope_lines = 0
    found = []
    seen = set()
    for line in lines:
        if HEADING.fullmatch(line[:140]):
            in_scope = True
            scope_lines = 0
            continue
        if in_scope and STOP.match(line):
            in_scope = False
        if in_scope:
            scope_lines += 1
            if scope_lines > 180:
                in_scope = False
        if not TECHNICAL.search(line):
            continue
        if not (ACTION.search(line) or (in_scope and BULLET.match(line))):
            continue
        clean = BULLET.sub("", line).strip()
        # Discard title fragments, header labels, and unmanageably long paragraphs.
        if not (28 <= len(clean) <= 450):
            continue
        # Without a technical section, require both a clear action and a technical term.
        # Avoid headings and ungrounded AI-generated interpretations.
        key = re.sub(r"\s+", " ", clean).casefold()
        if key not in seen:
            seen.add(key)
            found.append(clean)
        if len(found) >= max_items:
            break
    return found
