import json
from pathlib import Path

import run_pipeline


def test_safe_topic():
    assert run_pipeline.safe_topic("DigiLocker API/Integration") == "digilocker-api-integration"


def test_pipeline_reuses_stages(monkeypatch, tmp_path):
    def fake_scrape(topic, searxng, output, *args):
        Path(output).write_text(json.dumps({"topic": topic, "documents": []}), encoding="utf-8")
        return {"unique_candidates": 2, "pages_fetched": 1, "documents_downloaded": 0,
                "errors": [{"stage": "fetch", "error": "blocked"}]}

    def fake_extract(inp, output):
        Path(output).write_text(json.dumps({"topic": "DigiLocker", "documents": []}), encoding="utf-8")
        return {"documents": [], "errors": []}

    def fake_analyze(inp, output, model, ollama, timeout):
        Path(output).write_text(json.dumps({"topic": "DigiLocker", "results": []}), encoding="utf-8")
        return {"results": [], "errors": []}

    monkeypatch.setattr(run_pipeline, "scrape", fake_scrape)
    monkeypatch.setattr(run_pipeline, "extract", fake_extract)
    monkeypatch.setattr(run_pipeline, "analyze", fake_analyze)
    result = run_pipeline.execute("DigiLocker", tmp_path, model="qwen3:30b",
                                  ollama_url="http://localhost:11434", cppp=False)
    assert result["opportunity_count"] == 0
    assert len(result["issues"]) == 1
    assert Path(result["paths"]["consolidated"]).exists()


def test_pipeline_public_listing_capture(monkeypatch, tmp_path):
    def fake_cppp(topic):
        return {
            "sources": {"cppp_eprocure": "https://eprocure.gov.in/eprocure/app"},
            "matches": [{"title": "DigiLocker integration", "submission_deadline": None}],
            "coverage_note": "Only public listing subset.",
            "issues": [],
        }
    def fake_scrape(topic, searxng, output, *args):
        Path(output).write_text(json.dumps({"topic": topic, "documents": []}), encoding="utf-8")
        return {"unique_candidates": 0, "pages_fetched": 0, "documents_downloaded": 0, "errors": []}
    def fake_extract(inp, output):
        Path(output).write_text(json.dumps({"topic": "DigiLocker", "documents": []}), encoding="utf-8")
        return {"documents": [], "errors": []}
    def fake_analyze(inp, output, model, ollama, timeout):
        Path(output).write_text(json.dumps({"topic": "DigiLocker", "results": []}), encoding="utf-8")
        return {"results": [], "errors": []}
    monkeypatch.setattr(run_pipeline, "discover_public_listings", fake_cppp)
    monkeypatch.setattr(run_pipeline, "scrape", fake_scrape)
    monkeypatch.setattr(run_pipeline, "extract", fake_extract)
    monkeypatch.setattr(run_pipeline, "analyze", fake_analyze)
    result = run_pipeline.execute("DigiLocker", tmp_path, model="qwen3:30b", ollama_url="http://localhost:11434")
    assert len(result["public_listing_candidates"]) == 1
    saved = json.loads(Path(result["paths"]["consolidated"]).read_text(encoding="utf-8"))
    assert len(saved["public_listing_candidates"]) == 1
    assert saved["paths"]["consolidated"] == result["paths"]["consolidated"]
