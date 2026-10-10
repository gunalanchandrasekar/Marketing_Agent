import json
from signal_store import canonical, normalize, generate

def test_canonical_deduplicates_tracking_parameters():
    a=canonical("https://eprocure.gov.in/tender/?utm_source=email&id=7")
    b=canonical("https://eprocure.gov.in/tender?id=7")
    assert a==b

def test_uninspected_candidates_are_not_claimed_tenders():
    data=normalize("DigiLocker", {"candidates":[
        {"url":"https://example.com/article","search_queries":["DigiLocker tender"]}]})
    assert data["counts"]["needs_review"]==1
    assert data["signals"][0]["reason"].startswith("Search candidate")

def test_explainable_rejection_and_accepted_document():
    discovery={
        "candidates":[{"url":"https://example.com/manual","search_queries":[]},
                      {"url":"https://eprocure.gov.in/project/tender.pdf","search_queries":[]}],
        "pages":[{"url":"https://example.com/manual","title":"DigiLocker API specification",
                  "text":"DigiLocker API specification reference"}],
        "documents":[{"url":"https://eprocure.gov.in/project/tender.pdf","sha256":"abc"}],
    }
    result=normalize("DigiLocker",discovery)
    mapping={x["source_url"]:x for x in result["signals"]}
    assert mapping["https://example.com/manual"]["relevance_status"]=="rejected"
    assert mapping["https://eprocure.gov.in/project/tender.pdf"]["relevance_status"]=="accepted"
    assert mapping["https://eprocure.gov.in/project/tender.pdf"]["source_type"]=="official_government_domain"
    assert result["total"]==2

def test_generate_works_for_existing_runs(tmp_path):
    (tmp_path/"opportunities.json").write_text(json.dumps({"topic":"DigiLocker"}))
    (tmp_path/"results.json").write_text(json.dumps({"topic":"DigiLocker",
        "pages":[{"url":"https://example.org/digilocker-tender",
                  "title":"DigiLocker procurement tender","text":"Bid for DigiLocker"}]}))
    results=generate(tmp_path)
    assert results["coverage"]=="legacy_partial_candidates"
    assert (tmp_path/"signals.json").exists()
    assert results["total"]==1
