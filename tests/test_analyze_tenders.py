from analyze_tenders import deadline_status, select_context


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
