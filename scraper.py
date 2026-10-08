"""Phase 1: topic-driven public web discovery and document collection.

Usage:
    python scraper.py --topic DigiLocker
    python scraper.py --topic DigiLocker --searxng http://localhost:8081
    python scraper.py --topic DigiLocker --max-pages 20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, parse_qsl, urlencode, urlunparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
LOG = logging.getLogger("marketing_agent")
HEADERS = {"User-Agent": "MarketingAgentResearch/0.1 (public-document-discovery)"}
DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx")
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
MAX_TEXT_CHARS = 30000


def canonicalize(url: str) -> str:
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                             if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", query, ""))


def queries_for(topic: str) -> list[str]:
    phrase = f'"{topic}"'
    return [
        f'{phrase} tender OR RFP',
        f'{phrase} integration government tender',
        f'{phrase} request for proposal',
        f'{phrase} implementation services',
        f'{phrase} API integration requirement',
        f'{phrase} developer integration help',
        f'site:gov.in {phrase} tender',
        f'site:nic.in {phrase} RFP',
        f'site:github.com {phrase} integration',
        f'site:reddit.com {phrase} API',
        f'{phrase} site:ocac.in tender',
    ]


def search_searxng(client: httpx.Client, base: str, query: str, limit: int) -> list[str]:
    response = client.get(base.rstrip("/") + "/search", params={
        "q": query, "format": "json", "categories": "general"
    })
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise ValueError("SearXNG returned unexpected JSON")
    return [item["url"] for item in body["results"][:limit] if isinstance(item, dict) and isinstance(item.get("url"), str)]


def search_ddgs(query: str, limit: int) -> list[str]:
    from ddgs import DDGS
    with DDGS(timeout=20) as search:
        return [row["href"] for row in search.text(query, max_results=limit)
                if isinstance(row, dict) and row.get("href")]


def document_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(DOCUMENT_SUFFIXES)


def topic_match(topic: str, text: str) -> bool:
    """Reject unrelated pages, preserving flexible case/space/hyphen matching."""
    terms = re.findall(r"[a-z0-9]+", topic.lower())
    if not terms:
        return False
    normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
    return "".join(terms) in normalized


def candidate_priority(url: str) -> int:
    """Prefer Indian procurement sources over unrelated generic RFP listings."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path.lower()
    score = 0
    if host.endswith((".gov.in", ".nic.in", ".ac.in")) or host == "gov.in":
        score += 9
    if host.endswith(".in"):
        score += 3
    if any(x in host for x in ("ocac", "eprocure", "negd", "gem.gov")):
        score += 7
    if any(x in path for x in ("digilocker", "digi-locker")):
        score += 5
    if any(x in path for x in ("tender", "rfp", "rfq", "procurement", "bid")):
        score += 2
    return score


def eligible_document(url: str, topic: str, page_title: str, anchor_text: str) -> bool:
    """Only download linked documents that are likely connected to the topic."""
    hint = " ".join((urlparse(url).path, anchor_text))
    if topic_match(topic, hint):
        return True
    procurement = re.search(r"(?i)\b(rfp|rfq|tender|bid|corrigendum|expression.of.interest|eoi)\b", hint)
    return bool(procurement and topic_match(topic, page_title))


def extract_page(url: str, content: bytes) -> tuple[str, str, list[str]]:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    docs = []
    for anchor in soup.find_all("a", href=True):
        link = canonicalize(urljoin(url, anchor["href"]))
        if link and document_url(link):
            docs.append({"url": link, "anchor_text": anchor.get_text(" ", strip=True)[:200]})
    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()
    body = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", body)[:MAX_TEXT_CHARS]
    unique_docs = {row["url"]: row for row in docs}
    return title, text, list(unique_docs.values())


def download_document(client: httpx.Client, url: str, folder: Path, max_bytes: int) -> dict:
    """Stream documents with a hard size cap; never follow off-site file references as paths."""
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in DOCUMENT_SUFFIXES:
        raise ValueError("Not an allowed document extension")
    tmp = folder / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".partial")
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with tmp.open("wb") as out:
                for chunk in response.iter_bytes(65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Document exceeds size limit")
                    digest.update(chunk)
                    out.write(chunk)
        final = folder / (digest.hexdigest() + suffix)
        tmp.replace(final)
        return {"url": url, "path": str(final), "sha256": digest.hexdigest(), "bytes": total}
    finally:
        tmp.unlink(missing_ok=True)


def run(topic: str, searxng: str | None, output: Path, max_pages: int, max_docs: int,
        per_query: int, request_delay: float, max_document_mb: int) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    records, documents, errors = [], [], []
    urls: dict[str, set[str]] = {}
    queries = queries_for(topic)
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True, limits=limits) as client:
        for query in queries:
            try:
                found = (search_searxng(client, searxng, query, per_query)
                         if searxng else search_ddgs(query, per_query))
                for candidate in found:
                    url = canonicalize(candidate)
                    if url:
                        urls.setdefault(url, set()).add(query)
                LOG.info("Search OK: %s (%s results)", query, len(found))
            except Exception as exc:
                errors.append({"stage": "search", "query": query, "error": str(exc)})
                LOG.warning("Search failed: %s: %s", query, exc)
        doc_candidates = []
        for url, matched_queries in sorted(urls.items(), key=lambda pair: candidate_priority(pair[0]), reverse=True):
            if len(records) >= max_pages:
                break
            if document_url(url):
                if topic_match(topic, url) or re.search(r"(?i)(rfp|rfq|tender|corrigendum)", url):
                    doc_candidates.append((candidate_priority(url), url))
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                ct = response.headers.get("content-type", "").lower()
                if "html" not in ct and "text/plain" not in ct:
                    continue
                if len(response.content) > 5_000_000:
                    raise ValueError("Page exceeds 5 MB")
                title, text, doc_links = extract_page(str(response.url), response.content)
                if not topic_match(topic, title + " " + text):
                    LOG.info("Skipped off-topic page: %s", url)
                    continue
                relevant_docs = [row["url"] for row in doc_links
                                 if eligible_document(row["url"], topic, title, row["anchor_text"])]
                records.append({"url": url, "title": title, "text": text,
                                "search_queries": sorted(matched_queries), "document_links": relevant_docs})
                doc_candidates.extend((candidate_priority(url), link) for link in relevant_docs)
                LOG.info("Fetched relevant page %s, selected %d/%d documents", url, len(relevant_docs), len(doc_links))
            except Exception as exc:
                errors.append({"stage": "fetch", "url": url, "error": str(exc)})
                LOG.warning("Fetch failed: %s: %s", url, exc)
            time.sleep(max(0, request_delay))
        ranked_docs = sorted(doc_candidates, key=lambda pair: pair[0], reverse=True)
        for url in dict.fromkeys(link for _, link in ranked_docs):
            if len(documents) >= max_docs:
                break
            try:
                documents.append(download_document(client, url, output.parent / "documents",
                                                   max_document_mb * 1024 * 1024))
            except Exception as exc:
                errors.append({"stage": "download", "url": url, "error": str(exc)})
                LOG.warning("Download failed: %s: %s", url, exc)
            time.sleep(max(0, request_delay))
    result = {
        "topic": topic, "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "backend": "searxng" if searxng else "ddgs",
        "queries": queries,
        "unique_candidates": len(urls),
        "pages_fetched": len(records),
        "documents_downloaded": len(documents),
        "pages": records, "documents": documents, "errors": errors,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing Agent Phase 1 scraper")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--searxng", default=os.getenv("SEARXNG_URL") or None)
    parser.add_argument("--output", type=Path, default=Path("data/results.json"))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("MAX_PAGES", "40")))
    parser.add_argument("--max-documents", type=int, default=int(os.getenv("MAX_DOCUMENTS", "10")))
    parser.add_argument("--per-query", type=int, default=int(os.getenv("MAX_RESULTS_PER_QUERY", "8")))
    parser.add_argument("--delay", type=float, default=float(os.getenv("REQUEST_DELAY", "0.8")))
    parser.add_argument("--max-document-mb", type=int, default=int(os.getenv("MAX_DOCUMENT_MB", "20")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if min(args.max_pages, args.max_documents, args.per_query, args.max_document_mb) < 1:
        parser.error("limits must all be positive")
    result = run(args.topic, args.searxng, args.output, args.max_pages,
                 args.max_documents, args.per_query, args.delay, args.max_document_mb)
    print(f"Found {result['unique_candidates']} unique candidates; fetched "
          f"{result['pages_fetched']} pages; downloaded {result['documents_downloaded']} documents.")
    print(f"Errors: {len(result['errors'])}. Saved {args.output}")


if __name__ == "__main__":
    main()
