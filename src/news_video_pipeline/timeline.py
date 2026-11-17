from __future__ import annotations

import json
import wave
from pathlib import Path

from .models import Cue, Scene
from .tts import get_cached_audio


def make_audio_and_timeline(scenes: list[Scene], cfg: dict, workspace: Path, cache: Path) -> dict:
    rate = int(cfg["voice"]["sample_rate"])
    pause_frames = round(rate * int(cfg["voice"]["pause_ms"]) / 1000)
    target = workspace / "audio" / "narration.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    cues: list[Cue] = []
    recorded_scenes = []
    current = 0
    with wave.open(str(target), "wb") as destination:
        destination.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for scene in scenes:
            start = current
            for index, phrase in enumerate(scene.sentences):
                audio_path = get_cached_audio(phrase, cfg, cache)
                with wave.open(str(audio_path), "rb") as segment:
                    if (segment.getnchannels(), segment.getsampwidth(), segment.getframerate()) != (1, 2, rate):
                        raise ValueError(f"Unexpected WAV format: {audio_path}")
                    frames = segment.getnframes()
                    while True:
                        block = segment.readframes(16384)
                        if not block:
                            break
                        destination.writeframesraw(block)
                cues.append(Cue(scene.id, index, phrase, current, current + frames))
                current += frames
                if pause_frames:
                    destination.writeframesraw(b"\x00\x00" * pause_frames)
                    current += pause_frames
            recorded_scenes.append({
                "id": scene.id,
                "slide_index": len(recorded_scenes) + 1,
                "title": scene.title,
                "start_ms": round(start * 1000 / rate),
                "end_ms": round(current * 1000 / rate),
            })
    duration_ms = round(current * 1000 / rate)
    timeline = {
        "schema_version": 1,
        "sample_rate": rate,
        "duration_samples": current,
        "duration_ms": duration_ms,
        "scenes": recorded_scenes,
        "cues": [cue.to_dict(rate) for cue in cues],
    }
    (workspace / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    return timeline


def srt_time(ms: int) -> str:
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, remainder = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{remainder:03d}"


def write_srt(timeline: dict, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, cue in enumerate(timeline["cues"], 1):
        lines.extend([str(index), f"{srt_time(cue['start_ms'])} --> {srt_time(cue['end_ms'])}", cue["text"], ""])
    dest.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def validate_timeline(timeline: dict, expected_scene_count: int) -> None:
    scenes = timeline["scenes"]
    cues = timeline["cues"]
    if len(scenes) != expected_scene_count or not scenes or not cues:
        raise ValueError("Scene or subtitle count mismatch")
    previous_scene_end = 0
    for index, scene in enumerate(scenes, 1):
        if scene["slide_index"] != index or scene["start_ms"] != previous_scene_end:
            raise ValueError("Slides do not form a continuous timeline")
        if scene["end_ms"] <= scene["start_ms"]:
            raise ValueError("Scene has non-positive duration")
        previous_scene_end = scene["end_ms"]
    previous_cue_end = 0
    ids = {scene["id"]: scene for scene in scenes}
    for cue in cues:
        if cue["start_ms"] < previous_cue_end or cue["end_ms"] <= cue["start_ms"]:
            raise ValueError("Subtitle ordering or duration invalid")
        scene = ids[cue["scene_id"]]
        if not (scene["start_ms"] <= cue["start_ms"] < cue["end_ms"] <= scene["end_ms"]):
            raise ValueError("Subtitle not contained in its slide")
        previous_cue_end = cue["end_ms"]
    if previous_scene_end != timeline["duration_ms"]:
        raise ValueError("Timeline duration mismatch")
