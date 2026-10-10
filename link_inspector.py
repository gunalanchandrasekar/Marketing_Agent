"""Inspect explicitly supplied public URLs and collect relevant linked RFP documents.

URL ingestion is deliberately separate from nationwide topic discovery: articles,
awards and government portals are evidence sources, not automatically open tenders.
No login/CAPTCHA bypass, unbounded crawling, or private-network access.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from extract_tenders import read_document, evidence_candidates
from it_fit import it_fit
from relevance import PROCUREMENT
from scraper import download_document

MAX_HTML_BYTES = 2_000_000
MAX_DOC_BYTES = 18_000_000
MAX_LINKS_PER_PAGE = 50
USER_AGENT = {"User-Agent": "VAF-Market-Intelligence/1.0 (public-source-review)"}


def validate_public_url(value: str) -> str:
    """Reject localhost/private targets, credentials, custom ports and unsafe schemes.

    DNS is checked before every request/redirect; keep this backend on trusted LAN.
    """
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Provide an HTTP(S) public URL, maximum 2048 characters")
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are supported")
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError("Credentials and non-standard ports are not allowed")
    host = parsed.hostname.strip(".").lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Private/local hosts are not permitted")
    try:
        answers = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                     type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Source host cannot be resolved: {host}") from exc
    ips = [ipaddress.ip_address(item[4][0]) for item in answers]
    if not ips or any(not ip.is_global for ip in ips):
        raise ValueError("Source resolves to a non-public IP address")
    return value.strip()


def public_get(client: httpx.Client, url: str) -> tuple[bytes, str, str]:
    current = url
    for _ in range(5):
        validate_public_url(current)
        # Redirects are handled explicitly so destination is checked before visiting.
        with client.stream("GET", current, follow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                dest = response.headers.get("location")
                if not dest:
                    raise ValueError("Redirect has no destination")
                current = urljoin(current, dest)
                continue
            response.raise_for_status()
            ctype = response.headers.get("content-type", "").lower()
            if not ("html" in ctype or "pdf" in ctype or "octet-stream" in ctype
                    or "text/plain" in ctype or "application/msword" in ctype):
                raise ValueError(f"Unsupported source content type: {ctype[:80]}")
            limit = MAX_DOC_BYTES if "pdf" in ctype or ".pdf" in urlparse(current).path.lower() else MAX_HTML_BYTES
            pieces, size = [], 0
            for part in response.iter_bytes(65536):
                size += len(part)
                if size > limit:
                    raise ValueError("Source response exceeds safe download size")
                pieces.append(part)
            return b"".join(pieces), current, ctype
    raise ValueError("Too many redirects")


def parse_source(url: str, content: bytes) -> dict:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    summary = description.get("content", "").strip() if description else ""
    links = []
    for anchor in soup.find_all("a", href=True):
        target = urljoin(url, anchor["href"])
        parsed = urlparse(target)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            continue
        label = anchor.get_text(" ", strip=True)[:160]
        container = anchor.find_parent(["tr", "li", "article"]) or anchor.parent
        context = container.get_text(" ", strip=True)[:550] if container else ""
        links.append({"url": target.split("#")[0], "anchor_text": label, "context": context})
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:35000]
    unique = {item["url"]: item for item in links}
    return {"title": title or url, "description": summary, "text": body,
            "linked_urls": list(unique.values())[:MAX_LINKS_PER_PAGE]}


def relevant_documents(page: dict, source_url: str, max_documents: int = 8) -> list[dict]:
    """Use link label and surrounding listing context, not blind same-site crawling."""
    source_host = urlparse(source_url).hostname
    candidates = []
    for row in page.get("linked_urls", []):
        url = row["url"]
        path = urlparse(url).path.lower()
        # Portals commonly use /download?id=123 rather than .pdf URLs.
        dynamic_download = bool(re.search(r"/(?:download|downloadfile|attachment|getdocument)(?:/|$)", path))
        if not path.endswith((".pdf", ".docx")) and not dynamic_download:
            continue
        link_text = " ".join((url, row.get("anchor_text", ""), row.get("context", "")))
        # Avoid site banners, reports unrelated to the document subject and manuals.
        if re.search(r"\b(privacy policy|terms of use|cookie policy)\b", link_text, re.I):
            continue
        score = 0
        if PROCUREMENT.search(link_text):
            score += 4
        if re.search(r"(?i)\b(?:rfp|rfq|tender|bid|notification|notice|attachment|annexure|scope|specification)\b", link_text):
            score += 3
        if re.search(r"(?i)\b(?:api|integration|software|digilocker|platform|e-governance|IT services)\b", link_text):
            score += 3
        if urlparse(url).hostname == source_host:
            score += 1
        if row.get("anchor_text", "").lower() in ("pdf", "download", "document", "view document"):
            score += 2
        if score >= 2:
            candidates.append({**row, "score": score})
    return sorted(candidates, key=lambda x: -x["score"])[:max_documents]


def relevant_detail_pages(page: dict, parent_url: str, limit: int = 4) -> list[dict]:
    """Follow a few specifically relevant notice/detail links, never arbitrary site navigation."""
    origin = urlparse(parent_url).hostname
    results = []
    for link in page.get("linked_urls", []):
        target = link.get("url", "")
        parsed = urlparse(target)
        if parsed.hostname != origin or parsed.path.lower().endswith((".pdf", ".doc", ".docx")):
            continue
        label = " ".join([link.get("anchor_text", ""), link.get("context", ""), parsed.path])
        if re.search(r"(?i)\b(?:tender detail|tender notice|rfp|rfq|eoi|view tender|bid notice|procurement notice|download tender documents)\b", label):
            results.append(link)
        if len(results) >= limit:
            break
    return results


def save_pdf(content: bytes, uri: str, folder: Path) -> dict:
    if not content.lstrip().startswith(b"%PDF-"):
        raise ValueError("This document link did not return a valid PDF")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    path = folder / (digest + ".pdf")
    path.write_bytes(content)
    return {"url": uri, "sha256": digest, "path": str(path), "bytes": len(content)}


def inspect_links(
    urls: list[str], output_root: Path, model: str | None = None,
    ollama_url: str | None = None, max_documents: int = 8, progress=None,
) -> dict:
    if not 1 <= len(urls) <= 5:
        raise ValueError("Provide between 1 and 5 public URLs")
    if not 1 <= max_documents <= 12:
        raise ValueError("max_documents must be between 1 and 12")
    # Validate all first; no partial inspection from an invalid request.
    approved = [validate_public_url(url) for url in urls]
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = output_root / job_id
    directory.mkdir(parents=True, exist_ok=True)
    result = {
        "id": job_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "urls": approved, "sources": [], "documents": [], "issues": [],
        "verification_note": "Public source extraction only. Tender eligibility, deadline and awards require official verification.",
    }
    def save():
        (directory / "inspection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    seen_docs = set()
    try:
        with httpx.Client(headers=USER_AGENT, timeout=httpx.Timeout(25, connect=10), follow_redirects=False) as client:
            for index, address in enumerate(approved):
                if progress:
                    progress("fetching", f"Inspecting source {index + 1}/{len(approved)}", 10 + int(index * 40 / len(approved)))
                try:
                    content, resolved, ctype = public_get(client, address)
                    if content.lstrip().startswith(b"%PDF-"):
                        source = {"url": address, "resolved_url": resolved,
                                  "title": resolved.rsplit("/", 1)[-1], "kind": "PDF",
                                  "description": "", "text": "", "linked_urls": []}
                        attachments = [{"url": resolved, "anchor_text": "Supplied PDF", "score": 100}]
                    elif "html" in ctype or b"<html" in content[:200].lower():
                        page = parse_source(resolved, content)
                        source = {"url": address, "resolved_url": resolved,
                                  "title": page["title"], "kind": "Web page",
                                  "description": page["description"], "text": page["text"][:12000],
                                  "linked_urls": page["linked_urls"]}
                        attachments = relevant_documents(page, resolved, max_documents)
                        # A tender list often links to individual notice pages that
                        # themselves hold the RFP download button.
                        child_pages = []
                        for detail in relevant_detail_pages(page, resolved):
                            try:
                                child_content, child_url, child_type = public_get(client, detail["url"])
                                if "html" not in child_type and b"<html" not in child_content[:200].lower():
                                    continue
                                child = parse_source(child_url, child_content)
                                child_pages.append({
                                    "url": child_url, "title": child["title"],
                                    "description": child["description"],
                                    "text": child["text"][:6000],
                                })
                                attachments.extend(relevant_documents(child, child_url, max_documents))
                            except Exception as child_exc:
                                result["issues"].append({"stage": "linked_page", "url": detail["url"],
                                                        "error": str(child_exc)[:250]})
                        source["related_detail_pages"] = child_pages
                    else:
                        source = {"url": address, "resolved_url": resolved, "kind": "Other",
                                  "title": resolved, "description": "", "text": content.decode("utf-8", "replace")[:12000],
                                  "linked_urls": []}
                        attachments = []
                    source["it_fit"] = it_fit(source["title"], source.get("description") or source.get("text", "")[:3000])
                    result["sources"].append(source)
                    if len(result["documents"]) >= max_documents:
                        continue
                    for linked in attachments:
                        if len(result["documents"]) >= max_documents:
                            break
                        link = linked["url"]
                        if link in seen_docs:
                            continue
                        seen_docs.add(link)
                        try:
                            if link == resolved and content.lstrip().startswith(b"%PDF-"):
                                doc_content, final = content, resolved
                            else:
                                doc_content, final, _ = public_get(client, link)
                            if not final.lower().split("?")[0].endswith(".pdf") and not doc_content.lstrip().startswith(b"%PDF-"):
                                raise ValueError("Linked file is not a PDF; no unsupported converter attempted")
                            item = save_pdf(doc_content, final, directory / "documents")
                            item["source_page"] = resolved
                            text, page_count = read_document(Path(item["path"]))
                            item.update(page_count=page_count, text_characters=len(text),
                                        extraction_status="ok" if text.strip() else "no_embedded_text_ocr_needed",
                                        text=text[:170000], date_evidence=evidence_candidates(text))
                            result["documents"].append(item)
                        except Exception as exc:
                            result["issues"].append({"url": link, "stage": "download_or_extract", "error": str(exc)[:400]})
                except Exception as exc:
                    result["issues"].append({"url": address, "stage": "fetch", "error": str(exc)[:400]})
                save()
        if model and result["documents"]:
            if progress:
                progress("analyzing", "Extracting document requirements with Ollama", 75)
            # Reuse the existing tender analyzer; non-RFP articles remain signals.
            from analyze_tenders import analyze
            extracted = {"topic": "Direct Link", "documents": [
                {"document_url": d["url"], "sha256": d["sha256"], "text": d["text"],
                 "extraction_status": d["extraction_status"]}
                for d in result["documents"]
            ]}
            input_path = directory / "extracted_tenders.json"
            input_path.write_text(json.dumps(extracted, ensure_ascii=False), encoding="utf-8")
            analyzed = analyze(input_path, directory / "tender_analysis.json", model, ollama_url or "http://localhost:11434", 240)
            by_sha = {a["sha256"]: a["analysis"] for a in analyzed.get("results", [])}
            for item in result["documents"]:
                item["analysis"] = by_sha.get(item["sha256"])
            result["issues"].extend({"stage": "ai_analysis", **e} for e in analyzed.get("errors", []))
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        save()
        if progress:
            progress("complete", "Links reviewed", 100)
        return result
    except Exception:
        save()
        raise


def load_inspection(root: Path, inspection_id: str) -> dict:
    if not re.fullmatch(r"\d{8}T\d{12}Z", inspection_id):
        raise ValueError("Invalid inspection ID")
    path = root / inspection_id / "inspection.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Link inspection not found") from exc
