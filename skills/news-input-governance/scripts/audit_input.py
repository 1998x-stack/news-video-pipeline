#!/usr/bin/env python3
"""Read-only input audit; never claims factual or copyright verification."""
import argparse
import hashlib
import json
from pathlib import Path

def audit(path: Path) -> dict:
    if path.suffix.lower() not in {".md", ".txt", ".json"}:
        raise ValueError("Only .md, .txt, .json are supported")
    raw = path.read_bytes()
    if len(raw) > 3_000_000:
        raise ValueError("Input exceeds 3 MB")
    text = raw.decode("utf-8-sig")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
        if not isinstance(value, dict) or not isinstance(value.get("body"), str):
            raise ValueError("JSON input requires string body")
        title = str(value.get("title") or path.stem)
        body = value["body"].strip()
    else:
        lines = [s.strip() for s in text.splitlines() if s.strip()]
        if not lines:
            raise ValueError("Empty input")
        title = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else path.stem
        body = "\n".join(lines[1:] if lines[0].startswith("#") else lines)
    if not body:
        raise ValueError("Empty article body")
    return {"source_file": str(path), "title": title, "characters": len(body),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "facts_verified": False, "rights_status": "unverified",
            "public_release_approved": False}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    args = p.parse_args()
    print(json.dumps(audit(args.input), ensure_ascii=False, indent=2))
