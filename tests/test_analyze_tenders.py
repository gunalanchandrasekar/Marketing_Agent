from analyze_tenders import deadline_status, select_context, validate_evidence


def test_context_budget_and_evidence():
    text = "header " * 3000 + "Proposal submission deadline: 31st August 2026 " + " tail" * 5000
    result = select_context(text, "DigiLocker")
    assert len(result) <= 24000
    assert "Proposal submission deadline" in result


def test_bad_or_unknown_date():
    assert deadline_status(None) == "deadline_unknown_verify_official_portal"
    assert deadline_status("31st August 2026") == "deadline_unknown_verify_official_portal"


def test_past_deadline_is_not_declared_open():
    assert deadline_status("2020-08-31") == "original_deadline_passed_verify_corrigenda"


def test_evidence_validation():
    original = "Release of RFE\n7th August 2026\nProposal submission deadline 31st August 2026"
    evidence = {
        "publication_date": "Release of RFE 7th August 2026",
        "submission_deadline": "Proposal submission deadline 31st August 2026",
        "invented": "The proposal submission is on 15th September 2026"
    }
    result = validate_evidence(evidence, original)
    assert result["checked"] == 3
    assert result["matched"] == 2
    assert result["unmatched_fields"] == ["invented"]
