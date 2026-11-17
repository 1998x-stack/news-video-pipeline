#!/usr/bin/env python3
"""Tiered, reproducible smoke test for the news video pipeline.

Tiers are explicit so a paid or slow check never runs by accident:

    static      no network, no ffmpeg  (default)
    offline     heuristic planning only, no media, no network
    synthetic   full pipeline with sine-tone audio (technical closed loop only)
    tts         full pipeline with real offline speech (espeak-ng)
    llm         one real planner call  -- PAID/slow, needs OPENAI_* env
    llm-e2e     full pipeline with the real planner -- PAID/slow
    whisper     optional ASR similarity re-check (needs faster-whisper)

Examples:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --tier all-offline --report outputs/local/smoke.json
    python scripts/smoke_test.py --tier llm --input outputs/news/manuscript.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_environment import collect as collect_environment  # noqa: E402

TIER_ORDER = ["static", "offline", "synthetic", "tts", "llm", "llm-e2e", "whisper"]
TIER_ALIASES = {
    "all-offline": ["static", "offline", "synthetic", "tts"],
    "all": TIER_ORDER,
}
SAMPLE = "# 冒烟测试稿件\n\n这是一句用于技术闭环验证的测试文本。第二条句子用于确认采样时钟。\n\n换段之后进入第三个场景。"
KNOWN_LIMITATIONS = [
    "synthetic audio is a sine tone, never publishable speech",
    "whisper and edge TTS are optional and may be uninstalled",
    "technical qa_passed is not content, rights or publication approval",
]


class Skip(Exception):
    """A tier whose optional dependency is unavailable."""


# ------------------------------------------------------------------ checks

def _load_config():
    from news_video_pipeline.config import load_config

    return load_config()


def check_skill_catalog() -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts/validate_skills.py")],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"validate_skills failed: {out.stderr[-500:]}")
    return {"detail": out.stdout.strip()}


def check_configs() -> dict:
    from news_video_pipeline.config import load_config

    loaded = []
    for path in sorted((ROOT / "config").glob("*.yaml")):
        load_config(path)
        loaded.append(path.name)
    return {"detail": f"loaded {len(loaded)} configs: {', '.join(loaded)}"}


def check_package_imports() -> dict:
    import importlib

    modules = ["config", "models", "planner", "pipeline", "quality", "slides", "timeline", "tts", "video", "cli"]
    for name in modules:
        importlib.import_module(f"news_video_pipeline.{name}")
    return {"detail": f"{len(modules)} modules import"}


def check_heuristic_plan() -> dict:
    from news_video_pipeline.planner import plan, read_input

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "sample.md"
        source.write_text(SAMPLE, encoding="utf-8")
        title, body = read_input(source)
        scenes = plan(title, body, _load_config())
    sentences = sum(len(scene.sentences) for scene in scenes)
    if not scenes or not sentences:
        raise RuntimeError("heuristic planner produced nothing")
    return {"detail": f"{len(scenes)} scenes / {sentences} sentences", "scenes": len(scenes)}


def check_input_rejection() -> dict:
    from news_video_pipeline.planner import read_input

    with tempfile.TemporaryDirectory() as tmp:
        cases = 0
        empty = Path(tmp) / "empty.txt"
        empty.write_text("", encoding="utf-8")
        for candidate in (empty, Path(tmp) / "nope.txt", Path(tmp) / "bad.pdf"):
            try:
                read_input(candidate)
            except ValueError:
                cases += 1
            else:
                raise RuntimeError(f"{candidate} should have been rejected")
    return {"detail": f"{cases} invalid inputs rejected"}


def _full_run(provider: str, scale: float = 0.5) -> dict:
    from news_video_pipeline.pipeline import run, validate_existing
    from news_video_pipeline.quality import file_hash

    cfg = _load_config()
    cfg["voice"]["provider"] = provider
    cfg["render"]["width"] = int(1280 * scale)
    cfg["render"]["height"] = int(720 * scale)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "sample.md"
        source.write_text(SAMPLE, encoding="utf-8")
        started = time.time()
        target = run(source, Path(tmp) / "out", cfg)
        report = validate_existing(target, cfg)
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        hashes = {name: file_hash(target / name) for name in
                  ("timeline.json", "audio/narration.wav", "video/landscape.mp4")}
    return {
        "detail": (f"{report['scenes']} scenes, audio {report['audio_duration_ms']} ms, "
                   f"video {report['video_duration_ms']} ms, delta {report['duration_delta_ms']} ms, "
                   f"{time.time() - started:.1f}s"),
        "audio_duration_ms": report["audio_duration_ms"],
        "video_duration_ms": report["video_duration_ms"],
        "duration_delta_ms": report["duration_delta_ms"],
        "assets_verified": report["assets_verified"],
        "run_id": manifest["run_id"],
        "sha256": hashes,
        "publishable": False,
    }


def check_synthetic_e2e() -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise Skip("ffmpeg/ffprobe not installed")
    return _full_run("synthetic")


def check_real_tts_e2e() -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise Skip("ffmpeg/ffprobe not installed")
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        raise Skip("espeak-ng/espeak not installed")
    return _full_run("espeak")


def check_whisper() -> dict:
    import importlib.util

    if not importlib.util.find_spec("faster_whisper"):
        raise Skip("faster-whisper not installed (pip install '.[whisper]')")
    from news_video_pipeline.quality import transcript_similarity

    cfg = _load_config()
    cfg["voice"]["provider"] = "espeak"
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        raise Skip("espeak-ng/espeak not installed")
    with tempfile.TemporaryDirectory() as tmp:
        from news_video_pipeline.tts import synthesize

        wav = Path(tmp) / "one.wav"
        synthesize("这是一句用于识别核对的测试语音。", wav, cfg)
        score = transcript_similarity(wav, "这是一句用于识别核对的测试语音。", cfg)
    return {"detail": f"similarity {score:.3f}"}


def _llm_manuscript(input_path: Path | None):
    from news_video_pipeline.planner import read_input

    path = input_path or ROOT / "examples/sample_news.md"
    return read_input(path)


def check_llm_plan(input_path: Path | None = None) -> dict:
    import os

    cfg = _load_config()
    cfg["planner"]["provider"] = "openai-compatible"
    cfg["planner"]["model"] = os.getenv("OPENAI_MODEL", "")
    if not cfg["planner"]["model"] or not os.getenv("OPENAI_API_KEY"):
        raise Skip("OPENAI_API_KEY and OPENAI_MODEL must be set for the paid LLM tier")
    from news_video_pipeline.planner import grounding_report, llm_plan

    title, body = _llm_manuscript(input_path)
    started = time.time()
    scenes = llm_plan(title, body, cfg)
    elapsed = time.time() - started
    grounding = grounding_report(body, scenes)
    return {
        "detail": (f"{len(scenes)} scenes in {elapsed:.1f}s, source coverage "
                   f"{grounding['coverage']:.3f}, invented tokens {grounding['invented_tokens']}"),
        "model": cfg["planner"]["model"],
        "scenes": len(scenes),
        "seconds": round(elapsed, 1),
        "source_coverage": round(grounding["coverage"], 4),
        "invented_tokens": grounding["invented_tokens"],
    }


def check_llm_e2e(input_path: Path | None = None) -> dict:
    import os

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise Skip("ffmpeg/ffprobe not installed")
    cfg = _load_config()
    cfg["planner"]["provider"] = "openai-compatible"
    cfg["planner"]["model"] = os.getenv("OPENAI_MODEL", "")
    if not cfg["planner"]["model"] or not os.getenv("OPENAI_API_KEY"):
        raise Skip("OPENAI_API_KEY and OPENAI_MODEL must be set for the paid LLM tier")
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        raise Skip("espeak-ng/espeak not installed")
    from news_video_pipeline.pipeline import run, validate_existing

    cfg["voice"]["provider"] = "espeak"
    title, body = _llm_manuscript(input_path)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "manuscript.md"
        source.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        started = time.time()
        target = run(source, Path(tmp) / "out", cfg)
        report = validate_existing(target, cfg)
    return {
        "detail": (f"{report['scenes']} scenes, audio {report['audio_duration_ms']} ms, "
                   f"delta {report['duration_delta_ms']} ms, model {cfg['planner']['model']}, "
                   f"{time.time() - started:.1f}s"),
        "model": cfg["planner"]["model"],
        "tts": "espeak",
        "audio_duration_ms": report["audio_duration_ms"],
        "video_duration_ms": report["video_duration_ms"],
        "duration_delta_ms": report["duration_delta_ms"],
        "publishable": False,
    }


CHECKS: dict[str, list[tuple[str, object]]] = {
    "static": [("skill_catalog", check_skill_catalog), ("configs", check_configs),
               ("package_imports", check_package_imports)],
    "offline": [("heuristic_plan", check_heuristic_plan), ("input_rejection", check_input_rejection)],
    "synthetic": [("synthetic_e2e", check_synthetic_e2e)],
    "tts": [("real_tts_e2e", check_real_tts_e2e)],
    "llm": [("llm_plan", check_llm_plan)],
    "llm-e2e": [("llm_full_pipeline", check_llm_e2e)],
    "whisper": [("whisper_similarity", check_whisper)],
}


def run_tiers(tiers: list[str], input_path: Path | None = None) -> dict:
    needs_input = {"llm", "llm-e2e"}
    results = []
    for tier in tiers:
        for name, function in CHECKS[tier]:
            started = time.time()
            entry = {"tier": tier, "check": name}
            try:
                call = (lambda fn=function: fn(input_path)) if tier in needs_input else function
                entry.update({"status": "passed", **(call() or {})})
            except Skip as exc:
                entry.update({"status": "skipped", "detail": str(exc)})
            except Exception as exc:
                entry.update({"status": "failed", "detail": f"{type(exc).__name__}: {exc}",
                              "traceback": traceback.format_exc()[-1500:]})
            entry["seconds"] = round(time.time() - started, 2)
            print(f"[{entry['status']:7s}] {tier}/{name} {entry.get('detail', '')}")
            results.append(entry)
    return {
        "tiers": tiers,
        "checks": results,
        "summary": {state: sum(1 for r in results if r["status"] == state)
                    for state in ("passed", "failed", "skipped")},
        "known_limitations": KNOWN_LIMITATIONS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", action="append", choices=[*TIER_ORDER, *TIER_ALIASES],
                        help="Repeatable. Default: static")
    parser.add_argument("--input", type=Path, help="Manuscript for the LLM tiers")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    parser.add_argument("--no-environment", action="store_true", help="Skip the environment summary")
    args = parser.parse_args(argv)
    tiers: list[str] = []
    for requested in args.tier or ["static"]:
        for tier in TIER_ALIASES.get(requested, [requested]):
            if tier not in tiers:
                tiers.append(tier)
    environment = {} if args.no_environment else collect_environment()
    report = {"engine_version": environment.get("engine_version"),
              "environment": {k: environment.get(k) for k in
                              ("git_commit", "python", "pi", "ffmpeg", "espeak", "os", "architecture",
                               "credentials", "optional_python_deps")}}
    report.update(run_tiers(tiers, args.input))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    print(f"\nsummary: {report['summary']}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
        print(f"report: {args.report}")
    else:
        print(text)
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
