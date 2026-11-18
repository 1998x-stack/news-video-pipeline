# Editorial Quality — Acceptance and next local Pi verification

## Duration policy

- Default `editorial.duration_policy: warn`: 6–10 min is a **target**; long or short editorial videos can still have `status: qa_passed` as a purely **technical** QA result. The real duration, deviation, `target_met=false` and warning are in both QA and Manifest. Bounded revisions are attempted before accepting an over-budget script.
- Optional `editorial.duration_policy: strict`: script and PCM duration outside target trigger errors. Neither mode truncates narration, deletes a selected news story silently, or grants release approval.
- For the 2026-11-14 sample, the old 11.25-minute run did not meet the editorial target. Running new code will **not** retroactively prove 6–10 minutes; gather fresh real TTS/MP4 measurements.

## Human selection labels

Use `scripts/editorial_evaluate.py` with two independent label files from `docs/verification/editorial-human-evaluation.md`. Human relevance scores and a model's ranking are different sources of evidence. No collection of actual human labels was supplied in this PR: real Precision/NDCG = NOT RUN.

## Optional semantic risk triage

Use a separate config overlay (or copy to local YAML) with:

    editorial:
      semantic_review_mode: report
      duration_policy: warn

On a curated run, the model produces `semantic_review.json` with one review per claim and an exact supporting source excerpt when it says supported. Missing or invented excerpts fail validation; contradicting and insufficient judgments are **reports**, not independent verification. `strict` is opt-in to blocking unresolved FACT/INFERENCE items. Default `off` causes zero additional model calls.

Manual review must validate each critical fact, its original source and date, the analysis' inference, video materials/rights and publication decision. A self-review by the same gateway is neither a second source nor a certified NLI model.

## Local Pi evidence request

1. Re-fetch main, preserve uncommitted user work. Run unit, Skills, smoke, then one curated sample with real TTS and warn policy.
2. Record selected story IDs, initial/revised script character count, PCM duration, status/deviation, video output and fact review status.
3. Optionally run the semantic report with explicit API budget, record calls/errors/reviews. Try a known-negation adversarial test and keep the reviewer decision and human adjudication.
4. Gather blinded labels for at least 10 independent days from two humans; inspect inter-rater disagreements before fitting ranking weights.
5. Keep publication approval false, and report unavailable/not-run cases precisely.
