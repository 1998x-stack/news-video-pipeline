# Pi agent role specifications

Pi does not natively discover `.pi/agents/*.md` as subagents. Reusable role contracts are in the repository's `agents/` directory; Pi's native user-invocable equivalents live in `.pi/prompts/<name>.md` (e.g. `/news-producer`). For actual Pi subagent execution, install and review a suitable Pi extension separately; this project does not silently install executable extensions.
