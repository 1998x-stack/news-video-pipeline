#!/usr/bin/env python3
"""Statically inspect Skills, adapters, references, JSON templates and Python syntax."""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ["news-producer", "news-editorial-auditor", "news-storyboard-director",
          "news-timing-engineer", "news-qa-reviewer", "news-curator", "news-analyst"]
SKILL_COUNT = 11
# Backticked repo-relative resources that a Skill or adapter promises to the model.
# Only spans that are a single repo path (with a directory part) are treated as
# references, so bare artifact names like `qa_report.json` and placeholders like
# `skills/<id>/SKILL.md` are ignored.
BACKTICKED = re.compile(r"`([^`\n]+)`")
RESOURCE_SUFFIXES = (".md", ".json", ".py", ".yaml", ".yml", ".toml")


def referenced_resources(text):
    """Return the distinct repo-relative resource paths mentioned by a document."""
    found = set()
    for span in BACKTICKED.findall(text):
        token = span.strip()
        if any(character in token for character in " <>,;，、"):
            continue
        if ":" in token:
            head, _, tail = token.rpartition(":")
            if tail.isidentifier():
                token = head
        if "/" in token and token.endswith(RESOURCE_SUFFIXES):
            found.add(token)
    return sorted(found)


def missing_resources(text_source):
    """text_source: iterable of (label, text, base_dir). Returns unresolved paths."""
    missing = []
    for label, text, base in text_source:
        for relative in referenced_resources(text):
            candidates = [base / relative, ROOT / relative]
            if not any(candidate.exists() for candidate in candidates):
                missing.append(f"{label}: {relative}")
    return missing

def validate():
    skills = sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir())
    if len(skills) != SKILL_COUNT:
        raise ValueError(f"Expected exactly {SKILL_COUNT} canonical skills")
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
        unresolved = missing_resources([
            (f"skills/{folder.name}/SKILL.md", spec, folder),
            (f".agents/skills/{folder.name}/SKILL.md",
             (ROOT / ".agents/skills" / folder.name / "SKILL.md").read_text(encoding="utf-8"), ROOT),
            (f".claude/skills/{folder.name}/SKILL.md",
             (ROOT / ".claude/skills" / folder.name / "SKILL.md").read_text(encoding="utf-8"), ROOT),
        ])
        if unresolved:
            raise ValueError("Skill references a path that does not exist: " + "; ".join(unresolved))
    for name in AGENTS:
        paths = (f"agents/{name}.md", f".pi/prompts/{name}.md",
                 f".codex/agents/{name}.toml", f".claude/agents/{name}.md",
                 f".opencode/agents/{name}.md")
        for path in paths:
            if not (ROOT / path).is_file():
                raise ValueError(f"Missing role adapter: {path}")
        unresolved = missing_resources(
            [(path, (ROOT / path).read_text(encoding="utf-8"), ROOT) for path in paths])
        if unresolved:
            raise ValueError("Role adapter references a path that does not exist: " + "; ".join(unresolved))
    for file in (ROOT / "scripts").glob("*.py"):
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    return {"skills": len(skills), "agents": len(AGENTS), "status": "passed"}

if __name__ == "__main__":
    print(validate())
