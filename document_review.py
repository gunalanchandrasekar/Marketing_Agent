"""Safe per-run local PDF resolution and cited page snippets for document review."""
from __future__ import annotations
import re
from pathlib import Path
from pypdf import PdfReader


def find_document(run_dir: Path, sha256: str, records: list[dict]) -> dict:
    if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256 or ""):
        raise ValueError("Invalid document identifier")
    item = next((d for d in records if d.get("sha256") == sha256), None)
    if item is None:
        raise ValueError("Document not found in selected run")
    path = Path(item.get("local_path") or "")
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve()
    allowed = (run_dir.resolve() / "documents")
    if not resolved.is_relative_to(allowed) or not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise ValueError("Local PDF unavailable or outside selected run")
    return {"path": resolved, "document": item}


def page_evidence(path: Path, question: str, limit: int = 4) -> list[dict]:
    reader = PdfReader(str(path), strict=False)
    tokens = set(re.findall(r"[a-z0-9]{4,}", question.casefold())) - {
        "what", "which", "where", "when", "give", "this", "that", "about", "please",
        "explain", "tender", "document"
    }
    pages = []
    for number, page in enumerate(reader.pages, 1):
        body = page.extract_text() or ""
        if not body.strip():
            continue
        lowered = body.lower()
        score = sum(lowered.count(token) for token in tokens)
        if score:
            # Keep source passage near the matched question vocabulary.
            at = min((lowered.find(token) for token in tokens if token in lowered), default=0)
            excerpt = body[max(0,at-180):at+1300].strip()
        else:
            excerpt = body[:1000].strip()
        pages.append({"page": number, "score": score, "excerpt": excerpt})
    pages.sort(key=lambda p: (-p["score"], p["page"]))
    return [{"page": p["page"], "excerpt": p["excerpt"]} for p in pages[:limit]]
