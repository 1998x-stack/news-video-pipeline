#!/usr/bin/env python3
"""FFprobe must independently see both audio and video streams."""
import argparse
import json
import subprocess
from pathlib import Path

def audit(root: Path, max_delta_ms: float = 300) -> dict:
    video = root / "video/landscape.mp4"
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(video)], check=True, text=True,
                            capture_output=True, timeout=30)
    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise ValueError("Missing video track")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError("Missing audio track")
    timeline = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
    duration = float(info["format"]["duration"]) * 1000
    delta = abs(duration - timeline["duration_samples"] * 1000 / timeline["sample_rate"])
    if delta > max_delta_ms:
        raise ValueError(f"Video/audio duration delta {delta:.1f}ms exceeds {max_delta_ms}ms")
    return {"status": "passed", "duration_ms": round(duration),
            "duration_delta_ms": round(delta), "technical_review_only": True}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    p.add_argument("--max-delta-ms", type=float, default=300)
    a = p.parse_args()
    print(json.dumps(audit(a.output, a.max_delta_ms), ensure_ascii=False, indent=2))
