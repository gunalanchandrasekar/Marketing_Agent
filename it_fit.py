"""IT-services relevance checks for an IT consultancy's tender discovery.

Distinguish software/service procurement from paper card printing,
civil construction, consumables and unrelated physical supply.
"""
from __future__ import annotations
import re

IT_STRONG = re.compile(
    r"(?i)\b(?:api(?:s)?|software (?:development|solution|implementation|maintenance)|"
    r"system integration|integrat(?:ion|e|ing) (?:of |with )?(?:api|portal|application|system|digilocker|pan)|"
    r"web portal|citizen portal|digital platform|online application|"
    r"mobile app(?:lication)?|database (?:development|design|migration)|"
    r"data migration|cloud hosting|it infrastructure|network security|"
    r"cyber ?security|information technology services|"
    r"software as a service|e[- ]?governance|"
    r"identity verification api|pan verification api|"
    r"ocr software|e[- ]?sign integration|workflow automation|"
    r"application development|system modernization|"
    r"web[- ]based (?:system|application)|managed it services)\b"
)
IT_TECH = re.compile(
    r"(?i)\b(?:api|software|integration|integrate|portal|application|"
    r"database|digitization|digitalisation|cybersecurity|"
    r"cloud|hosting|ict|web platform|website|mobile app|"
    r"it services|information system|backend|frontend|"
    r"identity verification|data centre|data center)\b"
)
NON_IT = re.compile(
    r"(?i)\b(?:road works?|bridge construction|civil works?|"
    r"building renovation|concrete|bitumen|"
    r"printing (?:and |of )?(?:plastic |smart )?cards?|"
    r"blank (?:plastic )?cards?|"
    r"stationery|paper supply|toner cartridges?|"
    r"furniture|food grains?|ration supplies|"
    r"physical delivery of cards|lamination|"
    r"transport of materials|construction of|"
    r"office equipment supply)\b"
)

def it_fit(title: str | None, scope: str | None, technical: list[str] | None = None) -> dict:
    """Evaluate the actual project deliverables; never use department name as IT fit."""
    meaningful = " ".join([title or "", scope or ""] + [
        x for x in (technical or []) if isinstance(x, str)
    ])
    strong = bool(IT_STRONG.search(meaningful))
    weak = bool(IT_TECH.search(meaningful))
    physical = bool(NON_IT.search(meaningful))
    if strong:
        return {"status": "it_candidate", "reason": "Explicit software, API, integration or IT-service deliverable"}
    if physical and not weak:
        return {"status": "non_it", "reason": "Scope concerns physical supply, printing or construction without evidenced IT services"}
    if weak:
        return {"status": "review", "reason": "IT terminology present, but no clearly scoped IT implementation deliverable"}
    return {"status": "review", "reason": "No explicit IT-service deliverable established from extracted title and scope"}
