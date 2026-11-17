#!/usr/bin/env python3
"""Dependency-free static checks for the portable Skill and agent catalog."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["news-producer", "news-editorial-auditor", "news-storyboard-director",
          "news-timing-engineer", "news-qa-reviewer"]

def validate() -> dict:
    skills = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    if len(skills) != 9:
        raise ValueError(f"Expected nine Skills, got {len(skills)}")
    for folder in skills:
        spec = (folder / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", spec)
        if not match or match.group(1) != folder.name or len(match.group(2)) < 30:
            raise ValueError(f"Invalid skill frontmatter: {folder}")
        for directory in ("references", "assets", "scripts"):
            entries = list((folder / directory).iterdir())
            if not entries:
                raise ValueError(f"Missing {directory}: {folder}")
            for path in entries:
                if path.suffix == ".py":
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for name in AGENTS:
        if not (ROOT / "agents" / f"{name}.md").is_file():
            raise ValueError(f"Missing canonical role {name}")
        for native in (f".pi/prompts/{name}.md", f".claude/agents/{name}.md",
                       f".codex/agents/{name}.toml", f".opencode/agents/{name}.md"):
            if not (ROOT / native).is_file():
                raise ValueError(f"Missing agent adapter {native}")
    for folder in skills:
        for platform in (".agents", ".claude"):
            wrapper = ROOT / platform / "skills" / folder.name / "SKILL.md"
            if not wrapper.is_file() or folder.name not in wrapper.read_text(encoding="utf-8"):
                raise ValueError(f"Missing discovery wrapper {wrapper}")
    for script in (ROOT / "scripts").glob("*.py"):
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    return {"skills": len(skills), "agents": len(AGENTS),
            "canonical_stage_scripts": len(skills), "static_status": "passed"}

if __name__ == "__main__":
    print(validate())
