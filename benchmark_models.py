"""Benchmark installed Ollama models for quick, accurate tender JSON extraction.

Execute on the same network/machine as Ollama:
  python benchmark_models.py
Results are saved in data/model_benchmark.json and used by the dashboard.
This measures two controlled examples, not universal model intelligence.
"""
from __future__ import annotations
import argparse
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

def write_results(output: Path, results: list[dict], *, complete: bool) -> dict:
    ranked = sorted(results, key=lambda x: (-x["quality_points"], x["elapsed_seconds"]))
    # A partial benchmark must never override the previous model recommendation.
    winner = ranked[0]["model"] if complete and ranked and ranked[0]["quality_points"] >= 6 else None
    result = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "recommended_model": winner,
        "results": ranked,
        "method": "Two controlled tender classification/extraction examples; measured locally.",
        "note": "This small benchmark is a screening test, not proof of general model quality.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def benchmark(
    ollama_url: str = BASE, output: Path = OUTPUT,
    requested_models: list[str] | None = None,
    max_models: int = 3, request_timeout: float = 60.0,
) -> dict:
    results: list[dict] = []
    timeout = httpx.Timeout(request_timeout, connect=10.0)
    try:
        with httpx.Client(timeout=timeout) as client:
            tags = client.get(ollama_url + "/api/tags")
            tags.raise_for_status()
            installed = [m.get("name") for m in tags.json().get("models", []) if m.get("name")]
            if requested_models:
                unknown = [m for m in requested_models if m not in installed]
                if unknown:
                    raise ValueError("Models not installed in Ollama: " + ", ".join(unknown))
                models = requested_models
            else:
                # Exclude embedding, vision, cloud and tiny models from extraction benchmarking.
                models = [name for name in installed
                          if not any(token in name.lower() for token in (
                              "embed", "tinyllama", ":cloud", "vision", "deepseek-r1:1.5b"
                          ))][:max_models]
            if not models:
                raise ValueError("No suitable local extraction models found. Pass --models explicitly.")
            print(f"Benchmarking {len(models)} model(s) on {ollama_url}. "
                  f"Each request times out after {request_timeout:g}s.", flush=True)
            for index, model in enumerate(models, 1):
                scores, seconds, failures = [], [], []
                print(f"[{index}/{len(models)}] {model}", flush=True)
                for example_index, (prompt, reference, label) in enumerate(EXAMPLES, 1):
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
                        grade_value = grade(content, reference, label)
                        scores.append(grade_value)
                        print(f"  Example {example_index}/2: {grade_value}/4 in "
                              f"{time.monotonic() - start:.1f}s", flush=True)
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        scores.append(0)
                        failures.append(f"Example {example_index}: {type(exc).__name__}: {str(exc)[:170]}")
                        print(f"  Example {example_index}/2: failed ({type(exc).__name__})", flush=True)
                    seconds.append(time.monotonic() - start)
                results.append({
                    "model": model,
                    "quality_points": sum(scores),
                    "max_points": 8,
                    "elapsed_seconds": round(sum(seconds), 2),
                    "errors": failures,
                })
                write_results(output, results, complete=False)
    except KeyboardInterrupt:
        write_results(output, results, complete=False)
        print("\nBenchmark interrupted; completed model results saved. "
              "No model recommendation was selected.", flush=True)
        return write_results(output, results, complete=False)
    return write_results(output, results, complete=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare local Ollama models for tender JSON extraction")
    parser.add_argument("--ollama", default=BASE, help="Ollama base URL")
    parser.add_argument("--models", nargs="+", help="Exact installed models to test, e.g. qwen3:30b qwen2.5:32b")
    parser.add_argument("--max-models", type=int, default=3, help="Maximum installed models to test automatically")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout for each model inference in seconds")
    args = parser.parse_args()
    if args.max_models < 1 or args.timeout < 5:
        parser.error("--max-models must be positive and --timeout must be >= 5 seconds")
    try:
        outcome = benchmark(
            args.ollama.rstrip("/"), OUTPUT,
            requested_models=args.models,
            max_models=args.max_models, request_timeout=args.timeout,
        )
        print(json.dumps(outcome, indent=2))
    except (httpx.HTTPError, ValueError) as exc:
        parser.exit(1, f"Benchmark startup failed: {exc}\n")
