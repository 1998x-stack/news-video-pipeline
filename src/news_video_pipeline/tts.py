from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from . import __version__


def call(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {args[0]}: {result.stderr[-1200:]}")


def normalize_wav(src: Path, dst: Path, sample_rate: int) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg executable is required")
    call(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)])


def synthesize(text: str, dest: Path, config: dict) -> None:
    """Write a normalized mono s16 WAV. synthetic provider is ONLY a test fixture."""
    voice = config["voice"]
    provider = voice["provider"]
    rate = int(voice["sample_rate"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if provider == "synthetic":
        frames = max(rate // 2, int(rate * max(0.7, len(text) / 8)))
        with wave.open(str(dest), "wb") as stream:
            stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            for chunk_start in range(0, frames, 8192):
                # short test tone, NEVER publish as a voice track
                data = b"".join(struct.pack("<h", int(1600 * math.sin(2 * math.pi * 220 * i / rate))) for i in range(chunk_start, min(chunk_start + 8192, frames)))
                stream.writeframes(data)
        return
    with tempfile.TemporaryDirectory(prefix="news_video_tts_") as tmp:
        raw = Path(tmp) / ("raw.mp3" if provider == "edge" else "raw.wav")
        if provider == "espeak":
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise RuntimeError("espeak/espeak-ng is missing; install it or select edge voice provider")
            call([exe, "-v", str(voice["name"]), "-s", str(voice["rate"]), "-w", str(raw), text])
        elif provider == "edge":
            try:
                import edge_tts
            except ImportError as exc:
                raise RuntimeError("pip install '.[edge]' to enable edge TTS") from exc
            async def run():
                await edge_tts.Communicate(text, voice=str(voice["name"]), rate=str(voice.get("edge_rate", "+0%"))).save(str(raw))
            asyncio.run(run())
        normalize_wav(raw, dest, rate)


def get_cached_audio(text: str, config: dict, cache: Path) -> Path:
    voice = config["voice"]
    identity = {"text": text, "voice": voice, "engine_version": __version__}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"{digest}.wav"
    if output.exists() and output.stat().st_size > 44:
        return output
    temporary = cache / f".{digest}.{os.getpid()}.wav"
    try:
        synthesize(text, temporary, config)
        with wave.open(str(temporary), "rb") as fh:
            if fh.getframerate() != int(voice["sample_rate"]) or fh.getnchannels() != 1 or fh.getsampwidth() != 2 or fh.getnframes() <= 0:
                raise RuntimeError("TTS produced invalid WAV format")
        os.replace(temporary, output)
        return output
    finally:
        temporary.unlink(missing_ok=True)


def encode_mp3(source: Path, target: Path) -> None:
    call(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-codec:a", "libmp3lame", "-b:a", "192k", str(target)])
