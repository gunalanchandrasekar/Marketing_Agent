from extract_tenders import evidence_candidates


def test_dates_are_evidence_not_verified_fields():
    text = "Bid submission closing date: 19 October 2026 at 5 PM."
    result = evidence_candidates(text)
    assert result["submission_deadline"][0]["date_candidate"] == "19 October 2026"
    assert "closing date" in result["submission_deadline"][0]["evidence"]


def test_no_deadline_not_fabricated():
    result = evidence_candidates("DigiLocker API integration")
    assert not result["submission_deadline"]
