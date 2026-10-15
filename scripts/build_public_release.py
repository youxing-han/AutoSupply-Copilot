"""Build a reviewed application snapshot without exporting local Git history.

This never modifies the development repository or rewrites history. Use a new
output directory. Only committed, explicitly allowed application files enter
the snapshot; the caller separately initializes its public Git repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {"app.py", "public_app.py", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
       "requirements.txt", "requirements.lock.txt", "INSTALLATION.txt", ".gitignore",
       ".streamlit/config.toml", ".github/workflows/tests.yml"}
DOCS = {"docs/LOCAL_USAGE.md", "docs/DEPLOYMENT.md", "docs/RELEASE_AUDIT.md"}
SCREENSHOTS = {f"docs/screenshots/public-{mode}.jpg" for mode in ("single", "batch", "planning")}
SCREENSHOTS |= {f"docs/screenshots/online-{mode}.jpg" for mode in ("single", "batch", "planning", "mitigation")}


def allowed(path: str) -> bool:
    if path in TOP | DOCS | SCREENSHOTS:
        return True
    if path.startswith("agent/"):
        return Path(path).suffix in {".py", ".html", ".css"}
    if path.startswith("templates/"):
        return Path(path).suffix in {".csv", ".xlsx"}
    if path.startswith("tests/"):
        return Path(path).suffix == ".py"
    if path.startswith("docs/prototypes/"):
        return Path(path).suffix in {".py", ".html", ".md"}
    if path.startswith("scripts/"):
        return Path(path).suffix in {".py", ".ps1"}
    return False


def build(destination: Path) -> dict:
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Output directory already exists; choose a new directory.")
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=ROOT).decode().splitlines()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    selected = [path for path in paths if allowed(path)]
    missing = (TOP | DOCS | SCREENSHOTS) - set(selected)
    if missing:
        raise ValueError("Missing committed release files: " + ", ".join(sorted(missing)))
    destination.mkdir(parents=True)
    hashes = {}
    for relative in selected:
        content = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        hashes[relative] = hashlib.sha256(content).hexdigest()
    manifest = {"source_commit": revision, "file_count": len(selected), "sha256": hashes}
    (destination / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = build(args.destination)
    print(f"Exported {result['file_count']} reviewed files from {result['source_commit']}")
