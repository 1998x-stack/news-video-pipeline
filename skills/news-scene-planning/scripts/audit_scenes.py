#!/usr/bin/env python3
"""Read-only Scene structure audit; does not validate news facts."""
import argparse
import json
from pathlib import Path

def audit(path: Path) -> dict:
    scenes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Expected nonempty scenes array")
    seen = set()
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"Invalid scene {index}")
        sid = scene.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError(f"Missing or repeated id: {sid}")
        seen.add(sid)
        if not all(isinstance(scene.get(key), str) and scene[key].strip()
                   for key in ("title", "body")):
            raise ValueError(f"Empty title/body in {sid}")
        sentences = scene.get("sentences")
        if not isinstance(sentences, list) or not sentences or not all(
                isinstance(s, str) and s.strip() for s in sentences):
            raise ValueError(f"Invalid sentence list: {sid}")
    return {"status": "structurally_valid", "scenes": len(scenes),
            "sentences": sum(len(s["sentences"]) for s in scenes),
            "factual_review_required": True}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("scenes", type=Path, help="Path to scenes.json")
    print(json.dumps(audit(p.parse_args().scenes), ensure_ascii=False, indent=2))
