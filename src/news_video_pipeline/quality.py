from __future__ import annotations

import difflib
import hashlib
import json
import re
import wave
from pathlib import Path

from pptx import Presentation

from .timeline import validate_timeline
from .video import ffprobe


def file_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(data)
    return sha.hexdigest()


def transcript_similarity(audio: Path, expected: str, cfg: dict) -> float:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("pip install '.[whisper]' to enable Whisper QA") from exc
    model = WhisperModel(cfg["quality"]["whisper_model"], device=cfg["quality"]["whisper_device"], compute_type="int8")
    pieces, _ = model.transcribe(str(audio), language="zh", vad_filter=True)
    actual = "".join(piece.text for piece in pieces)
    def normalize(text: str) -> str:
        return "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))
    return difflib.SequenceMatcher(None, normalize(expected), normalize(actual)).ratio()


def validate_outputs(workspace: Path, scenes: list, timeline: dict, cfg: dict) -> dict:
    validate_timeline(timeline, len(scenes))
    expected = [workspace / "presentation" / "daily.pptx", workspace / "audio" / "narration.wav",
                workspace / "audio" / "narration.mp3", workspace / "subtitles" / "zh.srt",
                workspace / "timeline.json", workspace / "video" / "landscape.mp4"]
    missing = [str(x) for x in expected if not x.is_file() or x.stat().st_size < 10]
    if missing:
        raise ValueError(f"Missing/empty outputs: {missing}")
    pptx_count = len(Presentation(str(workspace / "presentation" / "daily.pptx")).slides)
    image_count = len(list((workspace / "presentation" / "slides").glob("slide_*.png")))
    if pptx_count != len(scenes) or image_count != len(scenes):
        raise ValueError("PPTX/PNG slide count does not match timeline")
    with wave.open(str(workspace / "audio" / "narration.wav"), "rb") as stream:
        duration = 1000 * stream.getnframes() / stream.getframerate()
    if abs(duration - timeline["duration_ms"]) > 1.1:
        raise ValueError("Audio timeline does not match PCM sample count")
    count = len(re.findall(r"(?m)^\d+\n\d{2}:\d{2}:\d{2},\d{3} -->", (workspace / "subtitles" / "zh.srt").read_text(encoding="utf-8")))
    if count != len(timeline["cues"]):
        raise ValueError("SRT cue count mismatch")
    info = ffprobe(workspace / "video" / "landscape.mp4")
    video_stream = next((x for x in info["streams"] if x.get("codec_type") == "video"), None)
    audio_stream = next((x for x in info["streams"] if x.get("codec_type") == "audio"), None)
    if not video_stream or not audio_stream:
        raise ValueError("MP4 does not contain both video and audio")
    if (int(video_stream["width"]), int(video_stream["height"])) != (int(cfg["render"]["width"]), int(cfg["render"]["height"])):
        raise ValueError("Incorrect MP4 resolution")
    rendered_ms = float(info["format"]["duration"]) * 1000
    drift = abs(rendered_ms - duration)
    if drift > float(cfg["quality"]["max_duration_diff_ms"]):
        raise ValueError(f"MP4 audio/timeline length drift is {drift:.1f} ms")
    if cfg["quality"]["whisper_check"]:
        expected_text = "".join(cue["text"] for cue in timeline["cues"])
        score = transcript_similarity(workspace / "audio" / "narration.wav", expected_text, cfg)
        if score < float(cfg["quality"]["min_transcript_similarity"]):
            raise ValueError(f"Whisper QA mismatch: {score:.3f}")
    else:
        score = None
    return {"status": "passed", "scenes": len(scenes), "cues": count, "audio_duration_ms": round(duration),
            "video_duration_ms": round(rendered_ms), "duration_delta_ms": round(drift), "whisper_similarity": score,
            "note": "Human editorial/source/rights review remains required before publication."}
