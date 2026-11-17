# OpenCode Skill compatibility

OpenCode discovers project `.agents/skills/*/SKILL.md` and `.claude/skills/*/SKILL.md` as compatible sources, so the repository avoids creating a third set of duplicate skill IDs here. Native agent profiles are in `.opencode/agents/*.md`. A standalone OpenCode-only installation via `python scripts/install_agents.py --platform opencode --target /path/to/project` copies complete canonical skills to `.opencode/skills/`.
