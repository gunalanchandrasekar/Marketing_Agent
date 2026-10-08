from scraper import canonicalize, document_url, extract_page, queries_for


def test_canonicalize():
    assert canonicalize("https://Example.COM/a?utm_source=x&b=2#top") == "https://example.com/a?b=2"
    assert canonicalize("file:///etc/passwd") == ""


def test_discovery_queries():
    q = queries_for("DigiLocker")
    assert any("tender" in term for term in q)
    assert any("github" in term for term in q)


def test_html_extraction():
    title, text, documents = extract_page("https://example.org/tender/", b"""
      <html><head><title>RFP Notice</title></head>
      <body><nav>skip</nav><p>DigiLocker API integration</p>
      <a href="../files/rfp.pdf">RFP</a></body></html>
    """)
    assert title == "RFP Notice"
    assert "DigiLocker API integration" in text
    assert documents == ["https://example.org/files/rfp.pdf"]


def test_document_link():
    assert document_url("https://example.com/notice.PDF?download=1")
    assert not document_url("https://example.com/notice.html")
