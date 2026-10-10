"""Critical user journey: chatbot must stay grounded when searches yield no readable PDFs."""
import json
from pathlib import Path

import web_dashboard


def test_chat_explains_missing_document_without_calling_ollama(tmp_path, monkeypatch):
    (tmp_path / "opportunities.json").write_text(
        json.dumps({"topic": "Ration Card", "opportunities": []}), encoding="utf-8"
    )
    (tmp_path / "extracted_tenders.json").write_text(
        json.dumps({"documents": []}), encoding="utf-8"
    )
    monkeypatch.setattr(web_dashboard, "get_run_dir", lambda run_id: tmp_path)
    monkeypatch.setattr(web_dashboard.httpx, "post", lambda *a, **k:
                        (_ for _ in ()).throw(AssertionError("Ollama must not be called")))
    result = web_dashboard.chat(web_dashboard.ChatInput(
        run_id="20261010T080000000000Z",
        message="What is the closing date?",
        model="qwen3:30b",
    ))
    assert result["evidence_available"] is False
    assert "no readable tender document text" in result["answer"].lower()
    assert "Web Discovery" in result["answer"]
