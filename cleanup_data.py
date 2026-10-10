"""Safely remove generated pipeline data, never source files or virtualenv.

Default: preview. Use --confirm to delete generated data/runs and legacy data JSON files.
"""
from __future__ import annotations
import argparse
import shutil
import json
from pathlib import Path

LEGACY = (
    "results.json", "results_v3.json", "results_v4.json",
    "extracted_tenders.json", "tender_analysis.json",
    "tender_analysis_v2.json", "tender_analysis_v3.json",
    "opportunities.json", "cppp_public_listings.json", "pipeline-ui.log",
)

def cleanup(data_root: Path, confirm: bool = False) -> list[str]:
    root = data_root.resolve()
    if root.name != "data":
        raise ValueError("Cleanup is restricted to a directory named data")
    targets = [root / "runs", root / "documents"]
    targets += [root / name for name in LEGACY]
    present = [p for p in targets if p.exists() and p.parent == root]
    if confirm:
        for target in present:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
    return [str(p) for p in present]

def archive_topic(data_root: Path, topic: str, confirm: bool = False) -> dict:
    """Move only matching generated runs out of active scans; recoverable."""
    from run_pipeline import safe_topic
    root = data_root.resolve()
    if root.name != "data" or not topic.strip():
        raise ValueError("Invalid data root or topic")
    folder = root / "runs" / safe_topic(topic)
    matches = []
    if folder.is_dir() and not folder.is_symlink():
        for run in folder.iterdir():
            metadata = run / "opportunities.json"
            if not run.is_dir() or run.is_symlink() or not metadata.is_file():
                continue
            try:
                meta = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(meta.get("topic", "")).strip().casefold() == topic.strip().casefold():
                matches.append(run)
    if confirm and matches:
        archive = root / "topic_trash" / safe_topic(topic)
        archive.mkdir(parents=True, exist_ok=True)
        for run in matches:
            destination = archive / run.name
            if destination.exists():
                raise FileExistsError("An archived run already has this identifier")
            run.rename(destination)
    return {"topic": topic.strip(), "run_count": len(matches),
            "run_ids": [p.name for p in matches], "archived": bool(confirm)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    paths = cleanup(Path(__file__).resolve().parent / "data", args.confirm)
    print(("Removed" if args.confirm else "Would remove") + f" {len(paths)} generated items:")
    for path in paths:
        print(" - " + path)
