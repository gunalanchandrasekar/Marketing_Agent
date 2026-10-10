from scraper import canonicalize, document_url, extract_page, queries_for, topic_match, eligible_document, eligible_link, balanced_candidates, candidate_priority, classify_page


def test_canonicalize():
    assert canonicalize("https://Example.COM/a?utm_source=x&b=2#top") == "https://example.com/a?b=2"
    assert canonicalize("file:///etc/passwd") == ""


def test_discovery_queries():
    q = queries_for("DigiLocker")
    assert any("tender" in term for term in q)
    assert any("Tripura" in term for term in q)
    assert any("Tamil Nadu" in term for term in q)
    assert any("eprocure.gov.in" in term for term in q)


def test_html_extraction():
    title, text, documents = extract_page("https://example.org/tender/", b"""
      <html><head><title>RFP Notice</title></head>
      <body><nav>skip</nav><p>DigiLocker API integration</p>
      <a href="../files/rfp.pdf">RFP</a></body></html>
    """)
    assert title == "RFP Notice"
    assert "DigiLocker API integration" in text
    assert len(documents) == 1
    assert documents[0]["url"] == "https://example.org/files/rfp.pdf"
    assert documents[0]["anchor_text"] == "RFP"


def test_document_link():
    assert document_url("https://example.com/notice.PDF?download=1")
    assert not document_url("https://example.com/notice.html")


def test_reject_unrelated_pages():
    assert not topic_match("DigiLocker", "County procurement and architectural policy")
    assert topic_match("DigiLocker", "Digi-Locker API integration")


def test_reject_unrelated_pdf_links():
    assert not eligible_document(
        "https://example.org/policy.pdf", "DigiLocker", "DigiLocker integration",
        "Architectural policy")
    assert eligible_document(
        "https://example.org/docs/tender.pdf", "DigiLocker", "DigiLocker integration RFP",
        "RFP document")
    assert not eligible_document(
        "https://example.org/files/DigiLocker-Specification.pdf", "DigiLocker", "Resources",
        "Specification")


def test_prioritization():
    assert candidate_priority("https://negd.gov.in/resource/digilocker-rfp") > candidate_priority(
        "https://www.example.com/procurement/")


def test_reference_docs_are_not_tenders():
    assert not eligible_document(
        "https://apisetu.gov.in/DigiLocker-Issuer-APISpecification-v1-13.pdf",
        "DigiLocker", "DigiLocker API resources", "API Specification")
    assert eligible_document(
        "https://digilocker.gov.in/assets/Public_notice_for_draft_RFE_Digilocker_v2.pdf",
        "DigiLocker", "DigiLocker News", "Download")
    assert classify_page("RFQ for DigiLocker integration", "") == "procurement"
    assert classify_page("DigiLocker integration guide", "") == "technical_reference"


def test_financial_quote_rfq_classified():
    assert classify_page("Request for Financial Quote (RFQ) for Integration of DigiLocker", "") == "procurement"


def test_generic_download_link_on_rfp():
    assert eligible_document(
        "https://example.gov.in/attachments/12345.pdf",
        "DigiLocker", "Request for Financial Quote for DigiLocker Integration",
        "PDF")
    assert not eligible_document(
        "https://example.gov.in/attachments/12345.pdf",
        "DigiLocker", "DigiLocker API Resources", "PDF")


def test_awards_not_active_procurement():
    assert classify_page("Final List of Agencies Selected for DigiLocker Integration", "") == "award_or_selection"


def test_broader_digilocker_queries_and_source_diversity():
    queries = queries_for("DigiLocker")
    assert any("cag.gov.in" in q for q in queries)
    assert any("citizen portal" in q for q in queries)
    candidates = {
        "https://a.gov.in/tender/1": {"x"},
        "https://a.gov.in/tender/2": {"x"},
        "https://b.gov.in/tender/1": {"x"},
    }
    ranked = balanced_candidates(candidates)
    assert len(ranked) == 3
    assert ranked[0][0].split("/")[2] != ranked[1][0].split("/")[2]


def test_generic_pdf_link_on_digilocker_tender_listing():
    page = b"""<html><head><title>Government Tenders</title></head><body>
      <table><tr><td>RFP for DigiLocker Integration Project</td>
      <td><a href="/uploads/12345.pdf">Download</a></td></tr></table></body></html>"""
    title, text, docs = extract_page("https://example.gov.in/tenders", page)
    assert eligible_link(docs[0], "DigiLocker", title, text)


def test_download_rejects_html_disguised_as_pdf(tmp_path):
    import pytest
    import httpx
    from scraper import download_document
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"<html>login</html>")
    )) as client:
        with pytest.raises(ValueError, match="non-PDF"):
            download_document(client, "https://example.gov.in/tender.pdf", tmp_path, 10000)
