from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def ffprobe(path: Path) -> dict:
    args = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    p = subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)
    return json.loads(p.stdout)


def render_video(images: list[Path], timeline: dict, audio: Path, destination: Path, cfg: dict) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")
    if len(images) != len(timeline["scenes"]):
        raise ValueError("Number of slides does not match timeline")
    # ffconcat scripts with duration and a terminal image keep the final image visible.
    destination.parent.mkdir(parents=True, exist_ok=True)
    concat = destination.parent / "slides.ffconcat"
    lines = ["ffconcat version 1.0"]
    for image, scene in zip(images, timeline["scenes"]):
        if "'" in str(image) or "\n" in str(image):
            raise ValueError("Output path must not include quote/newline for ffconcat")
        lines.append("file '" + str(image.resolve()) + "'")
        lines.append(f"duration {(scene['end_ms'] - scene['start_ms']) / 1000:.6f}")
    lines.append("file '" + str(images[-1].resolve()) + "'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    duration = timeline["duration_samples"] / timeline["sample_rate"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-safe", "0", "-f", "concat", "-i", str(concat),
        "-i", str(audio),
        "-filter_complex", f"[0:v]fps={int(cfg['render']['fps'])},format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", str(cfg["render"].get("preset", "veryfast")), "-crf", str(cfg["render"].get("crf", 22)),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{duration:.6f}",
        str(destination),
    ]
    p = subprocess.run(command, text=True, capture_output=True, timeout=int(cfg["render"].get("timeout_s", 1200)))
    if p.returncode:
        raise RuntimeError("FFmpeg render failed: " + p.stderr[-3000:])
    concat.unlink(missing_ok=True)
