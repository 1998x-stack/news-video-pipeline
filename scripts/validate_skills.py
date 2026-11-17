#!/usr/bin/env python3
"""Statically inspect Skills, adapters, references, JSON templates and Python syntax."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["news-producer", "news-editorial-auditor", "news-storyboard-director",
          "news-timing-engineer", "news-qa-reviewer"]

def validate():
    skills = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    if len(skills) != 9:
        raise ValueError("Expected exactly nine canonical skills")
    for folder in skills:
        spec = (folder / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", spec)
        if not front or front.group(1) != folder.name or len(front.group(2)) < 30:
            raise ValueError(f"Invalid Skill metadata: {folder}")
        for kind in ("references", "scripts", "assets"):
            children = list((folder / kind).iterdir())
            if not children:
                raise ValueError(f"Missing {kind}: {folder}")
            for file in children:
                if file.suffix == ".py":
                    ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
                elif file.suffix == ".json":
                    json.loads(file.read_text(encoding="utf-8"))
        for kind in (".agents", ".claude"):
            wrapper = ROOT / kind / "skills" / folder.name / "SKILL.md"
            if not wrapper.is_file():
                raise ValueError(f"Missing compatible Skill entry: {wrapper}")
    for name in AGENTS:
        for path in (f"agents/{name}.md", f".pi/prompts/{name}.md",
                     f".codex/agents/{name}.toml", f".claude/agents/{name}.md",
                     f".opencode/agents/{name}.md"):
            if not (ROOT / path).is_file():
                raise ValueError(f"Missing role adapter: {path}")
    for file in (ROOT / "scripts").glob("*.py"):
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    return {"skills": len(skills), "agents": len(AGENTS), "status": "passed"}

if __name__ == "__main__":
    print(validate())
