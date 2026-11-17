# Codex Skill compatibility

Current Codex scans `.agents/skills/<name>/SKILL.md` for project skills, not `.codex/skills`. This folder documents the compatibility choice while `.codex/agents/*.toml` provides project custom agents. Run `python scripts/install_agents.py --platform codex --target /path/to/project` to materialize canonical skills into `.agents/skills/` there.
