#!/usr/bin/env python3
"""Verify normalized narration WAV and PCM-sample timeline agreement."""
import argparse
import json
import wave
from pathlib import Path

def audit(root: Path) -> dict:
    timeline = json.loads((root / "timeline.json").read_text(encoding="utf-8"))
    with wave.open(str(root / "audio/narration.wav"), "rb") as wav:
        channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
    if (channels, width, rate) != (1, 2, int(timeline["sample_rate"])):
        raise ValueError("Narration must be mono signed 16-bit PCM at timeline sample rate")
    if frames != int(timeline["duration_samples"]):
        raise ValueError(f"Frame count mismatch: wav={frames}, timeline={timeline['duration_samples']}")
    if abs(round(frames * 1000 / rate) - int(timeline["duration_ms"])) > 1:
        raise ValueError("Audio duration mismatch")
    return {"status": "passed", "frames": frames, "sample_rate": rate,
            "duration_ms": round(frames * 1000 / rate),
            "voice_quality_and_rights_review_required": True}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    print(json.dumps(audit(p.parse_args().output), ensure_ascii=False, indent=2))
