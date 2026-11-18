#!/usr/bin/env python3
"""Inspect and optionally prune old, inactive pipeline staging directories.

Defaults to dry-run. Delete requires --delete; active flock holders, unknown
directory names, symlinks, completed manifests and fresh stages are protected.
No automatic pruning is performed during the production pipeline.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import time
from pathlib import Path

STAGING = re.compile(r"\.building-([a-f0-9]{16})-[A-Za-z0-9_-]+$")


def prune(root: Path, *, older_than_hours: float = 24, delete: bool = False) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Output root must be a real existing directory, not a symlink")
    if older_than_hours < (1 if delete else 0):
        raise ValueError("Delete requires >= 1 hour age; dry-run requires nonnegative age")
    root = root.resolve(strict=True)
    now = time.time()
    report = {"mode": "delete" if delete else "dry-run",
              "eligible": [], "deleted": [], "skipped": []}
    for item in sorted(root.iterdir()):
        match = STAGING.fullmatch(item.name)
        if not match:
            continue
        if item.is_symlink() or not item.is_dir():
            report["skipped"].append({"name": item.name, "reason": "not a real directory"})
            continue
        if (item / "manifest.json").exists():
            report["skipped"].append({"name": item.name, "reason": "contains manifest"})
            continue
        lock = root / f".{match.group(1)}.lock"
        if lock.is_symlink() or not lock.is_file():
            report["skipped"].append({"name": item.name, "reason": "missing or unsafe run lock"})
            continue
        # Lock before re-checking age; refuse to touch a concurrently running job.
        with lock.open("rb") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                report["skipped"].append({"name": item.name, "reason": "run is active"})
                continue
            try:
                if item.is_symlink() or not item.is_dir() or (item / "manifest.json").exists():
                    report["skipped"].append({"name": item.name, "reason": "changed during scan"})
                    continue
                hours = max(0.0, (now - item.stat().st_mtime) / 3600)
                if hours < older_than_hours:
                    report["skipped"].append({"name": item.name, "reason": "too recent"})
                    continue
                report["eligible"].append(item.name)
                if delete:
                    shutil.rmtree(item)
                    report["deleted"].append(item.name)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--older-than-hours", type=float, default=24)
    parser.add_argument("--delete", action="store_true",
                        help="Explicitly delete eligible failed/abandoned staging directories")
    args = parser.parse_args()
    result = prune(args.out, older_than_hours=args.older_than_hours, delete=args.delete)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
