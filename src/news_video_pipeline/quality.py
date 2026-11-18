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


def assert_curated_duration(duration_ms: float, cfg: dict) -> dict:
    """Strict real-PCM duration gate; never infer completion from script length."""
    minimum, maximum = map(int, cfg["editorial"]["target_duration_ms"])
    if not minimum <= duration_ms <= maximum:
        raise ValueError(
            f"Curated audio duration {duration_ms:.0f} ms is outside the "
            f"editorial.target_duration_ms window [{minimum}, {maximum}]; "
            "revise the script or voice settings instead of truncating the audio"
        )
    return {"duration_ms": round(duration_ms), "target_duration_ms": [minimum, maximum], "target_met": True}


def validate_editorial_artifacts(workspace: Path, scenes: list, cfg: dict) -> dict:
    """Check the curated-mode trail, including that no dropped story reached the video."""
    from .pipeline import EDITORIAL_ARTIFACTS

    missing = [name for name in EDITORIAL_ARTIFACTS if not (workspace / name).is_file()]
    if missing:
        raise ValueError(f"Curated mode is missing editorial artifact(s): {missing}")
    selection = json.loads((workspace / "editorial_selection.json").read_text(encoding="utf-8"))
    selected = list(selection.get("selected") or [])
    if not selected:
        raise ValueError("editorial_selection.json records no selected story")
    if len(selected) > int(selection.get("top_k", 0)):
        raise ValueError("editorial_selection.json selects more stories than top_k")
    claims = json.loads((workspace / "claims.json").read_text(encoding="utf-8"))
    briefs = json.loads((workspace / "analysis_briefs.json").read_text(encoding="utf-8"))
    if {brief["story_id"] for brief in briefs["briefs"]} != set(selected):
        raise ValueError("analysis_briefs.json does not cover exactly the selected stories")
    if int(claims.get("counts", {}).get("FACT", 0)) < 1:
        raise ValueError("claims.json records no FACT claim; the analysis is unsourced")
    # The scenes must narrate only the selected stories plus the hook and the close.
    allowed = set(selected) | {"opening", "closing"}
    strays = sorted({scene.source_id for scene in scenes if getattr(scene, "source_id", "") not in allowed})
    if strays:
        raise ValueError(f"Scenes narrate story id(s) {strays} that were not selected")
    script = (workspace / "editorial_script.md").read_text(encoding="utf-8")
    if len(script.strip()) < 200:
        raise ValueError("editorial_script.md is too short to be a 6-10 minute narration")
    return {
        "selected": selected,
        "insufficient": bool(selection.get("insufficient")),
        "claims": claims.get("counts"),
        "scenes_from_selection": len([scene for scene in scenes if getattr(scene, "source_id", "") in set(selected)]),
    }


def validate_outputs(workspace: Path, scenes: list, timeline: dict, cfg: dict,
                     editorial_artifacts: bool = False) -> dict:
    validate_timeline(timeline, len(scenes))
    expected = [workspace / "source.txt", workspace / "scenes.json",
                workspace / "presentation" / "daily.pptx", workspace / "audio" / "narration.wav",
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
    editorial = validate_editorial_artifacts(workspace, scenes, cfg) if editorial_artifacts else None
    if editorial is not None:
        editorial["duration"] = assert_curated_duration(duration, cfg)
    return {"status": "passed", "scenes": len(scenes), "cues": count, "audio_duration_ms": round(duration),
            "video_duration_ms": round(rendered_ms), "duration_delta_ms": round(drift), "whisper_similarity": score,
            "editorial": editorial,
            "note": "Human editorial/source/rights review remains required before publication."}
