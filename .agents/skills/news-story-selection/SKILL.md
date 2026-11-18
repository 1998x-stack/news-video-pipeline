---
name: news-story-selection
description: Select and rank the few Chinese news stories worth explaining, with a written reason for every drop.
---

# news-story-selection

This is the project-native discovery entrypoint. Before taking action, read the full canonical playbook at `skills/news-story-selection/SKILL.md` from this repository root. Follow its stage-specific steps, and load the referenced files under `skills/news-story-selection/references/` and `skills/news-story-selection/assets/`; only run its `scripts/` after checking inputs and capabilities.

The installed external-project distribution copies the entire canonical skill directory so the references, assets and scripts stay self-contained.

Never invent news facts, license permissions, audio timecodes or publication approval. Never pad a selection list or lower `planner.min_source_coverage` to make output pass. Report `insufficient` honestly, and do not claim future P1/P2 features have been implemented.
