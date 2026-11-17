#!/usr/bin/env python3
"""Verify technical output manifests; never authorize publication."""
import argparse
import hashlib
import json
from pathlib import Path

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fd:
        for chunk in iter(lambda: fd.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def audit(root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    qa = json.loads((root / "qa_report.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "qa_passed" or qa.get("status") != "passed":
        raise ValueError("Technical QA did not pass")
    assets = manifest.get("sha256")
    if not isinstance(assets, dict) or not assets:
        raise ValueError("Manifest has no file hashes")
    for name, digest in assets.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError("Malformed hash entry")
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Unsafe or missing asset: {name}")
        if hash_file(path) != digest:
            raise ValueError(f"Hash mismatch: {name}")
    return {"status": "technical_qa_passed", "files_checked": len(assets),
            "public_release_approved": bool(manifest.get("public_release_approved", False)),
            "rights_status": manifest.get("rights_status", "unknown"),
            "human_editorial_review_required": True}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    print(json.dumps(audit(p.parse_args().output), ensure_ascii=False, indent=2))
