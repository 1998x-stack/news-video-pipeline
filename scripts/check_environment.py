#!/usr/bin/env python3
"""Report the local toolchain needed to run the pipeline; never print secrets.

    python scripts/check_environment.py
    python scripts/check_environment.py --out outputs/local/environment.json
    python scripts/check_environment.py --strict   # exit 1 on a missing hard dependency

Secrets are reported as "set"/"unset" only. Values are never printed or written.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SECRET_ENV = ("OPENAI_API_KEY", "IAUTO_API_KEY", "ANTHROPIC_API_KEY", "EDGE_TTS_KEY")
HARD_REQUIREMENTS = ("ffmpeg", "ffprobe", "python>=3.10")


def version(command: list[str]) -> str | None:
    if not shutil.which(command[0]):
        return None
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    first = (out.stdout or out.stderr).strip().splitlines()
    return first[0].strip() if first else "unknown"


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def font_report() -> dict:
    try:
        from news_video_pipeline.config import load_config
        from news_video_pipeline.slides import font_path

        return {"resolved": font_path(load_config()), "status": "ok"}
    except Exception as exc:  # missing CJK font must be visible, not silent
        return {"resolved": None, "status": f"{type(exc).__name__}: {exc}"}


def config_report() -> dict:
    from news_video_pipeline.config import load_config

    out = {}
    for path in sorted((ROOT / "config").glob("*.yaml")):
        try:
            cfg = load_config(path)
            out[path.name] = {
                "status": "ok",
                "planner.provider": cfg["planner"]["provider"],
                "voice.provider": cfg["voice"]["provider"],
                "voice.sample_rate": cfg["voice"]["sample_rate"],
                "render": f"{cfg['render']['width']}x{cfg['render']['height']}@{cfg['render']['fps']}",
                "max_scenes": cfg["planner"]["max_scenes"],
                "whisper_check": cfg["quality"]["whisper_check"],
            }
        except Exception as exc:
            out[path.name] = {"status": f"INVALID: {type(exc).__name__}: {exc}"}
    return out


def collect() -> dict:
    import news_video_pipeline
    import news_video_pipeline.tts  # noqa: F401  (module import check)

    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    required = {
        "python>=3.10": sys.version_info >= (3, 10),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
    }
    disk = shutil.disk_usage(ROOT)
    return {
        "engine_version": news_video_pipeline.__version__,
        "git_commit": git_commit(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "pi": version(["pi", "--version"]),
        "ffmpeg": version(["ffmpeg", "-version"]),
        "ffprobe": version(["ffprobe", "-version"]),
        "docker": version(["docker", "--version"]),
        "espeak": version([espeak, "--version"]) if espeak else None,
        "git": version(["git", "--version"]),
        "font": font_report(),
        "disk_free_gb": round(disk.free / 1_000_000_000, 1),
        "optional_python_deps": {
            name: _module_available(module) for name, module in
            {"openai": "openai", "edge-tts": "edge_tts", "faster-whisper": "faster_whisper",
             "Pillow": "PIL", "python-pptx": "pptx", "PyYAML": "yaml"}.items()
        },
        "credentials": {name: ("set" if os.getenv(name) else "unset") for name in SECRET_ENV},
        "credentials_redacted": True,
        "configs": config_report(),
        "requirements": required,
    }


def _module_available(module: str) -> str:
    import importlib.util

    return "ok" if importlib.util.find_spec(module) else "missing"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a hard dependency is missing")
    args = parser.parse_args(argv)
    report = collect()
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    missing = [name for name, ok in report["requirements"].items() if not ok]
    if missing:
        print(f"MISSING hard requirements: {', '.join(missing)}", file=sys.stderr)
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
