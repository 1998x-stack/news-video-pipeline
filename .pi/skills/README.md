# Pi Skills discovery

Pi natively discovers repository `.agents/skills/*/SKILL.md`, so this project deliberately reuses that source **without duplicating the same skill IDs** under `.pi/skills`. Pi-native prompts are in `.pi/prompts/`. For a standalone Pi-only installation into another project, run `python scripts/install_agents.py --platform pi --target /path/to/project`; the installer materializes full Skills under `.pi/skills/`.
