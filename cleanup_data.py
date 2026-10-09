"""Safely remove generated pipeline data, never source files or virtualenv.

Default: preview. Use --confirm to delete generated data/runs and legacy data JSON files.
"""
from __future__ import annotations
import argparse
import shutil
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    paths = cleanup(Path(__file__).resolve().parent / "data", args.confirm)
    print(("Removed" if args.confirm else "Would remove") + f" {len(paths)} generated items:")
    for path in paths:
        print(" - " + path)
