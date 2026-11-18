"""Editorial intelligence for the news video pipeline (curated-analysis mode).

The package follows one rule: Python owns boundaries, arithmetic, thresholds,
deduplication and range checks; the LLM proposes content through schema-checked
structured calls whose claims are then verified against the source text.
"""
