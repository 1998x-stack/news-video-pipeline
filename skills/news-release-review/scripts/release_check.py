#!/usr/bin/env python3
"""Print non-authorizing release checklist; exits 2 if not approved."""
import argparse
import json
from pathlib import Path

CHECKS = ("Source verified by human", "All claims and quotes checked",
          "Footage, artwork, voice and music rights cleared",
          "Sensitive material, identities and fairness reviewed",
          "Video audio/subtitles/visuals watched by reviewer",
          "Platform account permissions reviewed",
          "Explicit reviewer signature tied to output hash recorded")

def main(root: Path) -> int:
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"run_id": data.get("run_id"),
                      "technical_status": data.get("status"),
                      "public_release_approved": data.get("public_release_approved", False),
                      "rights_status": data.get("rights_status", "unknown"),
                      "human_checklist": CHECKS,
                      "note": "No publishing/authorization performed"}, ensure_ascii=False, indent=2))
    return 2 if data.get("public_release_approved") is not True else 0

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    raise SystemExit(main(p.parse_args().output))
