#!/usr/bin/env python3
"""Independently verify scene/cue continuity and SRT count."""
import argparse
import json
import re
from pathlib import Path

def audit(root: Path) -> dict:
    timeline = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
    scenes, cues = timeline["scenes"], timeline["cues"]
    if not scenes or not cues:
        raise ValueError("Empty scene/cue list")
    previous = 0
    ids = {}
    for index, scene in enumerate(scenes, 1):
        if scene["id"] in ids or scene["slide_index"] != index or scene["start_ms"] != previous or scene["end_ms"] <= previous:
            raise ValueError(f"Invalid or discontinuous scene {index}")
        previous = scene["end_ms"]
        ids[scene["id"]] = scene
    if previous != timeline["duration_ms"]:
        raise ValueError("Last scene does not meet timeline duration")
    prior = 0
    for index, cue in enumerate(cues, 1):
        start, end = cue["start_ms"], cue["end_ms"]
        scene = ids.get(cue["scene_id"])
        if scene is None or start < prior or end <= start or start < scene["start_ms"] or end > scene["end_ms"]:
            raise ValueError(f"Invalid cue {index}")
        prior = end
    subtitles = (root / "subtitles/zh.srt").read_text(encoding="utf-8")
    count = len(re.findall(r"(?m)^\d+\n\d{2}:\d{2}:\d{2},\d{3} -->", subtitles))
    if count != len(cues):
        raise ValueError(f"SRT count mismatch: {count} != {len(cues)}")
    return {"status": "passed", "scenes": len(scenes), "cues": len(cues),
            "duration_ms": timeline["duration_ms"], "word_alignment_implemented": False}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    print(json.dumps(audit(p.parse_args().output), ensure_ascii=False, indent=2))
