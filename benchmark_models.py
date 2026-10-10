"""Benchmark installed Ollama models for quick, accurate tender JSON extraction.

Execute on the same network/machine as Ollama:
  python benchmark_models.py
Results are saved in data/model_benchmark.json and used by the dashboard.
This measures two controlled examples, not universal model intelligence.
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434").rstrip("/")
OUTPUT = Path(__file__).resolve().parent / "data" / "model_benchmark.json"

EXAMPLES = [
    ("Document: REQUEST FOR PROPOSAL: PAN card verification API integration. "
     "Reference: IT/PAN/2026/17. The department shall integrate PAN verification "
     "APIs. Closing date: 30 October 2026. Extract title, reference, and one "
     "technical requirement.",
     "IT/PAN/2026/17", "pan"),
    ("Document: Annual staff attendance circular. General office instructions. "
     "No tender, bid, RFP or quotation is being invited. Classify whether this "
     "is a procurement tender and do not invent a reference.",
     None, "not_tender"),
]
SYSTEM = (
    "You are a procurement analyst. Respond as JSON only with keys "
    "tender_title, tender_reference, technical_requirements (array), "
    "is_procurement (boolean). Never invent missing information."
)

def grade(response: dict, expected_ref: str | None, topic: str) -> int:
    if not isinstance(response, dict):
        return 0
    if expected_ref:
        return int(str(response.get("tender_reference") or "").strip() == expected_ref) * 2 + (
            int(response.get("is_procurement") is True) +
            int(any(topic in str(x).lower() for x in response.get("technical_requirements") or []))
        )
    return int(response.get("is_procurement") is False) * 3 + int(
        not response.get("tender_reference")
    )

def benchmark(ollama_url: str = BASE, output: Path = OUTPUT) -> dict:
    with httpx.Client(timeout=httpx.Timeout(180, connect=10)) as client:
        tags = client.get(ollama_url + "/api/tags")
        tags.raise_for_status()
        models = [m.get("name") for m in tags.json().get("models", [])
                  if m.get("name") and not any(
                      x in m.get("name", "").lower() for x in
                      ("embed", "tinyllama", ":cloud", "vision")
                  )]
        results = []
        for model in models:
            scores, seconds, failures = [], [], []
            for prompt, reference, label in EXAMPLES:
                start = time.monotonic()
                try:
                    response = client.post(ollama_url + "/api/chat", json={
                        "model": model, "stream": False, "format": "json",
                        "think": False, "options": {"temperature": 0, "num_predict": 320},
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": prompt},
                        ],
                    })
                    response.raise_for_status()
                    content = json.loads(response.json()["message"]["content"])
                    scores.append(grade(content, reference, label))
                    seconds.append(time.monotonic() - start)
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    failures.append(str(exc)[:200])
                    scores.append(0)
            results.append({
                "model": model, "quality_points": sum(scores),
                "max_points": 8, "elapsed_seconds": round(sum(seconds), 2),
                "errors": failures,
            })
    # Quality has priority; among similarly accurate models choose lower latency.
    ranked = sorted(results, key=lambda x: (-x["quality_points"], x["elapsed_seconds"]))
    winner = ranked[0]["model"] if ranked and ranked[0]["quality_points"] >= 6 else None
    result = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "recommended_model": winner,
        "results": ranked,
        "method": "Two deterministic tender classification/extraction examples; speed measured on local hardware.",
        "note": "Not proof of general model superiority. Rebenchmark after changing hardware or models.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

if __name__ == "__main__":
    outcome = benchmark()
    print(json.dumps(outcome, indent=2))
