from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .pipeline import run, validate_existing
from .planner import plan, read_input


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="news-video", description="Article/news manuscript → PPTX + TTS + SRT + timeline + MP4")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--input", required=True, type=Path)
        p.add_argument("--config", type=Path)
        p.add_argument("--planner", choices=("heuristic", "openai-compatible"))
        p.add_argument("--tts", choices=("espeak", "edge", "synthetic"))
        if name == "run":
            p.add_argument("--out", type=Path, default=Path("outputs"))
            p.add_argument("--source-url", default="")
            p.add_argument("--force", action="store_true")
    check = sub.add_parser("validate")
    check.add_argument("output", type=Path)
    check.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "validate":
            print(json.dumps(validate_existing(args.output, cfg), ensure_ascii=False, indent=2))
            return 0
        if args.planner:
            cfg["planner"]["provider"] = args.planner
        if args.tts:
            cfg["voice"]["provider"] = args.tts
        if args.command == "plan":
            title, body = read_input(args.input)
            scenes = plan(title, body, cfg)
            print(json.dumps({"title": title, "scenes": [x.to_dict() for x in scenes]}, ensure_ascii=False, indent=2))
            return 0
        if cfg["voice"]["provider"] == "synthetic":
            print("WARNING: synthetic provider generates test tones, NOT speech. DO NOT PUBLISH.", file=sys.stderr)
        result = run(args.input, args.out, cfg, force=args.force, source_url=args.source_url)
        print(json.dumps({"result": "qa_passed", "directory": str(result), "manifest": str(result / 'manifest.json')}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"ERROR {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
