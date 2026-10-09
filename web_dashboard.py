"""VAF Opportunity Intelligence web UI. Run: python web_dashboard.py

Binds to localhost only. UI reads existing pipeline outputs and can start/retry jobs.
Not suitable for exposure to the public internet without authentication.
"""
from __future__ import annotations
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from run_pipeline import execute, safe_topic
from retry_analysis import retry
from cleanup_data import cleanup

BASE = Path(__file__).resolve().parent
RUNS = BASE / "data" / "runs"
WEB = BASE / "web" / "index.html"
app = FastAPI(title="VAF Opportunity Intelligence", docs_url=None, redoc_url=None)
pool = ThreadPoolExecutor(max_workers=1)
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = threading.Lock()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def list_runs() -> list[dict]:
    found = []
    for path in sorted(RUNS.glob("*/*/opportunities.json"), reverse=True):
        data = read_json(path)
        if not data.get("run_id"):
            continue
        steps = data.get("steps") or {}
        found.append({
            "run_id": data["run_id"],
            "topic": data.get("topic", ""),
            "finished_at": data.get("finished_at"),
            "opportunities": len(data.get("opportunities") or []),
            "downloaded": (steps.get("discovery") or {}).get("documents_downloaded", 0),
            "analyzed": (steps.get("analysis") or {}).get("documents_analyzed", 0),
        })
    return found[:50]


def get_run_dir(run_id: str) -> Path:
    if not run_id.isdigit() and not (len(run_id) == 22 and run_id.endswith("Z")):
        raise HTTPException(status_code=400, detail="Invalid run ID")
    matches = list(RUNS.glob("*/" + run_id + "/opportunities.json"))
    if len(matches) != 1:
        raise HTTPException(status_code=404, detail="Run not found")
    return matches[0].parent


def run_detail(run_dir: Path) -> dict:
    result = read_json(run_dir / "opportunities.json")
    if not result:
        raise HTTPException(status_code=404, detail="No consolidated data")
    extract_data = read_json(run_dir / "extracted_tenders.json")
    docs = []
    for item in extract_data.get("documents", []):
        docs.append({
            "document_url": item.get("document_url"),
            "sha256": item.get("sha256"),
            "page_count": item.get("page_count"),
            "text_characters": item.get("text_characters"),
            "extraction_status": item.get("extraction_status"),
        })
    listing = read_json(run_dir / "cppp_public_listings.json")
    result["documents"] = docs
    result["public_listing_candidates"] = listing.get("matches", result.get("public_listing_candidates", []))
    return result


class ScanInput(BaseModel):
    topic: str = Field(min_length=2, max_length=120)
    model: str = Field(default="qwen3:30b", min_length=2, max_length=100)
    max_pages: int = Field(default=20, ge=1, le=60)
    max_documents: int = Field(default=5, ge=1, le=12)


class RetryInput(BaseModel):
    model: str = Field(default="qwen3:30b", min_length=2, max_length=100)
    timeout: int = Field(default=1200, ge=60, le=3600)


def start_job(kind: str, fn) -> dict:
    with jobs_lock:
        if any(v["status"] in ("queued", "running") for v in jobs.values()):
            raise HTTPException(status_code=409, detail="A job is already running")
        job_id = uuid.uuid4().hex[:12]
        jobs[job_id] = {"id": job_id, "kind": kind, "status": "queued", "message": "Queued", "stage": "queued", "percent": 0}
    def task():
        with jobs_lock:
            jobs[job_id]["status"] = "running"
            jobs[job_id]["message"] = "Processing. This can take several minutes."
        try:
            def progress(stage, message, percent):
                with jobs_lock:
                    jobs[job_id].update(stage=stage, message=message, percent=percent)
            result = fn(progress)
            with jobs_lock:
                jobs[job_id].update(status="complete", stage="complete", percent=100, message="Completed", result=result)
        except Exception as exc:
            with jobs_lock:
                jobs[job_id].update(status="failed", message=str(exc)[:500])
    pool.submit(task)
    return {"job_id": job_id, "status": "queued"}


@app.get("/")
def home():
    return FileResponse(WEB, media_type="text/html")


@app.get("/api/models")
def models():
    url = os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434").rstrip("/")
    try:
        response = httpx.get(url + "/api/tags", timeout=7)
        response.raise_for_status()
        names = [m.get("name") for m in response.json().get("models", []) if m.get("name") and "embedding" not in m.get("capabilities", [])]
        return {"models": names, "connected": True, "server": url}
    except (httpx.HTTPError, ValueError) as exc:
        return {"models": [], "connected": False, "server": url, "error": str(exc)}


@app.get("/api/runs")
def runs():
    return {"runs": list_runs()}


@app.get("/api/runs/{run_id}")
def details(run_id: str):
    return run_detail(get_run_dir(run_id))


@app.post("/api/scans")
def scan(params: ScanInput):
    topic = params.topic.strip()
    if len(topic) < 2:
        raise HTTPException(422, detail="Topic is required")
    def action(progress):
        result = execute(
            topic, RUNS, model=params.model,
            ollama_url=os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434"),
            max_pages=params.max_pages, max_documents=params.max_documents, timeout=1200,
            progress=progress,
        )
        return {"run_id": result["run_id"], "opportunities": result["opportunity_count"]}
    return start_job("scan", action)


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: str, params: RetryInput):
    run_dir = get_run_dir(run_id)
    def action(progress):
        progress("analyzing", "Retrying unfinished Ollama analyses", 35)
        result = retry(
            run_dir, params.model,
            os.getenv("OLLAMA_BASE_URL", "http://192.168.0.100:11434"),
            params.timeout,
        )
        progress("saving", "Updated analysis results", 95)
        return {"run_id": run_id, "opportunities": result["opportunity_count"]}
    return start_job("retry", action)


@app.post("/api/data/cleanup")
def cleanup_generated():
    with jobs_lock:
        if any(j["status"] in ("queued", "running") for j in jobs.values()):
            raise HTTPException(409, detail="Wait for the current scan to finish before cleanup")
    removed = cleanup(BASE / "data", confirm=True)
    return {"removed": len(removed), "paths": removed}


@app.get("/api/jobs/{job_id}")
def job_info(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Unknown job")
        return jobs[job_id].copy()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8502, log_level="info")
