#!/usr/bin/env python3
"""Install the canonical news-video Skills and native Agent adapters.

Default is a project-local, non-destructive install. Never overwrite a different
file without --force. User-scope paths follow each agent's official layout.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    "pi": (".pi/skills", ".pi/prompts", ".pi/agent/skills", ".pi/agent/prompts"),
    "codex": (".agents/skills", ".codex/agents", ".agents/skills", ".codex/agents"),
    "claude": (".claude/skills", ".claude/agents", ".claude/skills", ".claude/agents"),
    "opencode": (".opencode/skills", ".opencode/agents", ".config/opencode/skills", ".config/opencode/agents"),
}
NATIVE_AGENT_SOURCE = {
    "pi": ROOT / ".pi/prompts",
    "codex": ROOT / ".codex/agents",
    "claude": ROOT / ".claude/agents",
    "opencode": ROOT / ".opencode/agents",
}

def items(platforms: list[str], scope: str, base: Path, components: str) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for platform in platforms:
        project_skills, project_agents, user_skills, user_agents = PLATFORMS[platform]
        rel_skills, rel_agents = (project_skills, project_agents) if scope == "project" else (user_skills, user_agents)
        # Pi and OpenCode can consume the shared Codex .agents/skills sources.
        # In an all-platform installation, avoid redundant IDs where possible.
        inherited = (
            (platform == "pi" and "codex" in platforms) or
            (platform == "opencode" and ("codex" in platforms or "claude" in platforms))
        ) if scope == "project" else False
        if components in {"all", "skills"} and not inherited:
            for folder in sorted((ROOT / "skills").iterdir()):
                if folder.is_dir() and (folder / "SKILL.md").is_file():
                    for source in sorted(folder.rglob("*")):
                        if source.is_file():
                            pairs.append((source, base / rel_skills / folder.name / source.relative_to(folder)))
        if components in {"all", "agents"}:
            for source in sorted(NATIVE_AGENT_SOURCE[platform].iterdir()):
                if source.is_file() and source.suffix in {".md", ".toml"}:
                    pairs.append((source, base / rel_agents / source.name))
    return pairs

def write_file(source: Path, dest: Path, *, force: bool, dry_run: bool, source_repo: bool) -> str:
    if source.is_symlink():
        raise ValueError(f"Refusing source symlink: {source}")
    parent = dest.parent
    for node in (parent, *parent.parents):
        if node.is_symlink():
            raise ValueError(f"Refusing destination symlink parent: {node}")
    if dest.is_symlink():
        raise ValueError(f"Refusing destination symlink: {dest}")
    original = source.read_bytes()
    if dest.is_file():
        if dest.read_bytes() == original:
            return "unchanged"
        # The repo has intentionally lightweight native discovery wrappers.
        # Do not replace tracked wrappers during an in-repository installation.
        if source_repo:
            return "built-in-adapter"
        if not force:
            raise FileExistsError(f"Would overwrite {dest}; pass --force intentionally")
    if dry_run:
        return "would-write"
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".news-skill-", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "written"

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--platform", choices=("all", *PLATFORMS), action="append",
                   help="Repeat for multiple platforms; default: all")
    p.add_argument("--scope", choices=("project", "user"), default="project")
    p.add_argument("--target", type=Path, help="Project root; default: this repository")
    p.add_argument("--components", choices=("all", "skills", "agents"), default="all")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="Replace differing installed files; never delete extra files")
    p.add_argument("--list", action="store_true", help="Show available skill and agent names")
    a = p.parse_args(argv)
    if a.list:
        print("Skills:", ", ".join(x.name for x in sorted((ROOT / "skills").iterdir()) if (x / "SKILL.md").is_file()))
        print("Agents:", ", ".join(x.stem for x in sorted((ROOT / "agents").glob("*.md"))))
        return 0
    if a.scope == "user" and a.target is not None:
        p.error("--target is only valid with --scope project")
    selections = list(PLATFORMS) if not a.platform or "all" in a.platform else list(dict.fromkeys(a.platform))
    base = (a.target or ROOT).expanduser().resolve() if a.scope == "project" else Path.home()
    source_repo = a.scope == "project" and base == ROOT
    planned = items(selections, a.scope, base, a.components)
    counts = {"written": 0, "would-write": 0, "unchanged": 0, "built-in-adapter": 0}
    try:
        for source, dest in planned:
            result = write_file(source, dest, force=a.force, dry_run=a.dry_run, source_repo=source_repo)
            counts[result] += 1
    except (ValueError, OSError) as exc:
        print(f"INSTALL ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"target={base} platforms={','.join(selections)} scope={a.scope} "
          f"components={a.components} dry_run={a.dry_run} {counts}")
    if source_repo and counts["built-in-adapter"]:
        print("Repository already has discovery wrappers; use an external --target for fully materialized copies.")
    print("This installs instructions and scripts only; it does not authorize execution or publication.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
