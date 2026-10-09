from retry_analysis import consolidate

def test_recovery_merges_and_clears_only_resolved_errors():
    state = {"topic": "DigiLocker", "opportunities": [], "issues": [
        {"stage": "analysis", "document_url": "a", "error": "timed out"},
        {"stage": "download", "url": "b", "error": "timed out"}]}
    result = {"results": [{"document_url": "a", "sha256": "123",
              "analysis": {"tender_title": "Sample", "deadline_status": "original_deadline_passed_verify_corrigenda"}}],
              "errors": []}
    merged = consolidate(state, result)
    assert merged["opportunity_count"] == 1
    assert len(merged["issues"]) == 1
    assert merged["issues"][0]["stage"] == "download"
