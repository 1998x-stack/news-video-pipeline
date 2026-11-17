#!/usr/bin/env python3
"""Safe CLI adapter: plan is default and full generation is explicit."""
import argparse
import subprocess
import sys
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("outputs"))
    p.add_argument("--config", type=Path)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--tts", choices=("espeak", "edge", "synthetic"))
    a = p.parse_args()
    cmd = [sys.executable, "-m", "news_video_pipeline.cli",
           "plan" if a.plan_only else "run", "--input", str(a.input)]
    if a.config:
        cmd += ["--config", str(a.config)]
    if a.tts:
        cmd += ["--tts", a.tts]
    if a.run:
        cmd += ["--out", str(a.out)]
        if a.force:
            cmd.append("--force")
    elif a.force:
        p.error("--force is only valid with --run")
    return subprocess.run(cmd, check=False).returncode

if __name__ == "__main__":
    sys.exit(main())
