import json

import httpx
import pytest
from fastapi.testclient import TestClient

import link_inspector
import web_dashboard


def test_extracts_related_tender_pdfs_from_public_source():
    html = b"""<html><head><title>Procurement notices</title>
    <meta name="description" content="Public procurement notices"></head>
    <body><table><tr><td>RFP for DigiLocker API integration</td>
    <td><a href="/rfps/digilocker.pdf">Download PDF</a></td></tr></table>
    <a href="/privacy">Privacy policy</a></body></html>"""
    page = link_inspector.parse_source("https://example.gov.in/tenders", html)
    matches = link_inspector.relevant_documents(page, "https://example.gov.in/tenders")
    assert len(matches) == 1
    assert matches[0]["url"] == "https://example.gov.in/rfps/digilocker.pdf"
    assert "API integration" in matches[0]["context"]


def test_detects_detail_pages_without_crawling_unrelated_navigation():
    html = b"""<html><body><a href="/tender-detail/987">View Tender Details</a>
    <a href="/contact">Contact us</a><a href="https://elsewhere.com/rfp">RFP</a></body></html>"""
    page = link_inspector.parse_source("https://example.gov.in/notices", html)
    selected = link_inspector.relevant_detail_pages(page, "https://example.gov.in/notices")
    assert len(selected) == 1
    assert "tender-detail" in selected[0]["url"]


def test_public_url_rejects_internal_hosts_without_dns():
    for url in ("file:///etc/passwd", "http://localhost:8080", "http://127.0.0.1/",
                "http://192.168.0.100:11434", "http://user:pass@example.com", "ftp://example.com"):
        with pytest.raises(ValueError):
            link_inspector.validate_public_url(url)


def test_public_url_requires_public_dns(monkeypatch):
    import socket
    monkeypatch.setattr(link_inspector.socket, "getaddrinfo",
                        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM,
                                                  6, "", ("10.2.3.4", 443))])
    with pytest.raises(ValueError, match="non-public"):
        link_inspector.validate_public_url("https://example.com/private")


def test_redirect_to_private_destination_is_not_fetched(monkeypatch):
    monkeypatch.setattr(link_inspector, "validate_public_url",
                        lambda u: (_ for _ in ()).throw(ValueError("blocked"))
                        if "192.168." in u else u)
    requested = []
    def fake_response(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://192.168.1.1/private"})
    with httpx.Client(transport=httpx.MockTransport(fake_response)) as client:
        with pytest.raises(ValueError, match="blocked"):
            link_inspector.public_get(client, "https://example.gov.in/redirect")
    assert len(requested) == 1


def test_link_routes_validate_and_keep_independent_saved_history(monkeypatch, tmp_path):
    monkeypatch.setattr(web_dashboard, "BASE", tmp_path)
    inspection = tmp_path / "data" / "link_inspections" / "20261010T120000123456Z"
    inspection.mkdir(parents=True)
    (inspection / "inspection.json").write_text(json.dumps({
        "id": inspection.name, "urls": ["https://example.gov.in/tenders"],
        "created_at": "2026-10-10T12:00:00Z", "sources": [{
            "title": "Procurement notices", "url": "https://example.gov.in/tenders"
        }], "documents": [], "issues": [],
    }))
    client = TestClient(web_dashboard.app)
    history = client.get("/api/links/history")
    assert history.status_code == 200
    assert history.json()["inspections"][0]["id"] == inspection.name
    detail = client.get("/api/links/" + inspection.name)
    assert detail.status_code == 200
    assert detail.json()["sources"][0]["title"] == "Procurement notices"


def test_link_intelligence_screen_exists():
    html = web_dashboard.WEB.read_text(encoding="utf-8")
    assert 'data-page="links"' in html
    assert 'id="view-links"' in html
    assert "function submitLinkInspection(event)" in html
    assert "function openLinkInspection(id)" in html


def test_non_pdf_article_is_saved_as_research_signal(monkeypatch, tmp_path):
    page = b"""<html><head><title>IT company wins API platform award</title>
    <meta name="description" content="Award for a government digital integration platform"></head>
    <body><article><p>New system integration project announced.</p></article></body></html>"""
    monkeypatch.setattr(link_inspector, "validate_public_url", lambda u: u)
    monkeypatch.setattr(link_inspector, "public_get",
                        lambda client, url: (page, url, "text/html; charset=utf-8"))
    result = link_inspector.inspect_links(
        ["https://news.example/award"], tmp_path, model=None
    )
    assert len(result["sources"]) == 1
    assert result["sources"][0]["title"] == "IT company wins API platform award"
    assert result["documents"] == []
    assert result["issues"] == []
    loaded = link_inspector.load_inspection(tmp_path, result["id"])
    assert loaded["sources"][0]["description"].startswith("Award for")
