"""CPPP public-listing adapter. No CAPTCHA solving or protected searches.

Fetches the publicly displayed eProcure/ePublish homepage tender listings.
Coverage is limited to the listings presented on those pages (NOT all live tenders).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from scraper import HEADERS, topic_match

SOURCES = {
    "cppp_eprocure": "https://eprocure.gov.in/eprocure/app?page=Home&service=page",
    "cppp_epublish": "https://eprocure.gov.in/epublish/app?service=home",
}
SEARCH_PAGE = "https://eprocure.gov.in/eprocure/app?page=FrontEndAdvancedSearch&service=page"
DATE_RE = re.compile(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)\b", re.I)
REF_RE = re.compile(r"\b(?:GEM/\d{4}/B/\d+|\d{4}_[A-Z]+\_\d+)\b")


def extract_home_listings(html: str, base_url: str, topic: str, source: str) -> list[dict]:
    """Match rows using title/reference content, never a generic page-body hit."""
    soup = BeautifulSoup(html, "html.parser")
    records = []
    seen = set()
    for table in soup.find_all("table"):
        header = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
        if not re.search(r"tender|closing|reference", header, re.I):
            continue
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            # Allow row ordinal in first column and use later fields for title.
            title_idx = 1 if len(cells) >= 5 and texts[0].rstrip(".").isdigit() else 0
            if len(texts) <= title_idx + 2:
                continue
            title = texts[title_idx]
            reference = texts[title_idx + 1]
            closing = texts[title_idx + 2]
            if not topic_match(topic, title + " " + reference):
                continue
            if not title or len(title) > 1000:
                continue
            anchor = cells[title_idx].find("a", href=True) or tr.find("a", href=True)
            href = urljoin(base_url, anchor["href"]) if anchor else base_url
            # Accept only official eprocure.gov.in links from HTML.
            host = urlparse(href).hostname or ""
            if host not in ("eprocure.gov.in", "www.eprocure.gov.in"):
                href = base_url
            key = (reference.casefold(), title.casefold())
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "source": source,
                "official_listing_url": base_url,
                "tender_url": href,
                "title": title,
                "tender_reference": reference or None,
                "closing_date_display": closing or None,
                "submission_deadline": None,
                "deadline_status": "unverified_official_detail_required",
                "verification_status": "public_listing_only_verify_official_tender_detail",
                "source_kind": "official_public_listing",
            })
    return records


def discover_public_listings(topic: str, timeout: int = 20) -> dict:
    items = []
    issues = []
    with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
        for source, url in SOURCES.items():
            try:
                response = client.get(url)
                response.raise_for_status()
                if len(response.content) > 5_000_000:
                    raise ValueError("HTML exceeds 5MB safety limit")
                items.extend(extract_home_listings(response.text, str(response.url), topic, source))
            except (httpx.HTTPError, ValueError) as exc:
                issues.append({"stage": "cppp_public_listing", "source": source, "url": url, "error": str(exc)})
    return {
        "topic": topic,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": SOURCES,
        "captcha_search_url": SEARCH_PAGE,
        "coverage_note": "Homepage lists only a subset of notices. Keyword/advanced search requires manual CAPTCHA and is not automated.",
        "matches": items,
        "issues": issues,
    }
