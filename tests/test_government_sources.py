from web_dashboard import government_source_records, is_official_government_url


def test_govt_issued_rfp_shows_even_if_no_cppp_listing():
    run = {"opportunities": [{
        "title": "Ration Card Supply RFP",
        "issuing_authority": "Department of Food and Supplies, Government of NCT of Delhi",
        "tender_reference": "2014_FSCAD_54051_1",
        "submission_deadline": "2014-03-31",
        "deadline_status": "original_deadline_passed_verify_corrigenda",
        "document_url": "https://example.com/tender.pdf",
    }]}
    records = government_source_records(run, [])
    assert len(records) == 1
    assert records[0]["category"] == "Government-issued RFP (AI identified)"
    assert records[0]["source_status"] == "Third-party or unverified document host"


def test_official_host_is_verified_by_hostname_not_keyword():
    assert is_official_government_url("https://eprocure.gov.in/eprocure/app")
    assert is_official_government_url("https://tenders.tripura.gov.in/notice")
    assert not is_official_government_url("https://fakegov.in/tender")
    assert not is_official_government_url("https://example.org/government-rfp")
