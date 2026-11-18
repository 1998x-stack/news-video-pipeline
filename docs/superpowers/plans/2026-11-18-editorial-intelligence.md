# Editorial Intelligence (curated-analysis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI news-chief-editor layer that extracts every story from a full 新闻联播 manuscript, ranks them by an explainable rubric, selects 3–5 deliberately, and produces an analytical script that the existing media core turns into a 6–10 minute video.

**Architecture:** New `editorial/` package of small modules, each with one responsibility and one artifact on disk. Deterministic Python owns boundaries, arithmetic, thresholds, dedupe and range checks; the LLM proposes content through schema-validated, span-checked structured calls. The media core (`slides`, `tts`, `timeline`, `video`, `quality`) is not modified; it consumes the same `Scene[]` it always did.

**Tech Stack:** Python 3.12, stdlib dataclasses/re, `openai` (optional extra), PyYAML, pytest; FFmpeg + espeak-ng only in the media stages.

**Spec:** `docs/superpowers/specs/2026-11-18-editorial-intelligence-design.md`

## Global Constraints

- Never invent news facts, citations, organisations or dates; user input is the only fact source.
- PCM sample count is the only time baseline. No speed-estimate or MP3-duration patching.
- `Scene` → PPTX/PNG; sentence WAV → timeline/SRT/MP3/MP4. Data-model changes bump `schema_version` and ship tests.
- Fail closed: missing/invalid files, scene overflow, invalid audio, decode failure, misaligned subtitles raise; never pass as `qa_passed`.
- No silent truncation of input; no lowering of `planner.min_source_coverage`.
- Tests that need no online API must always run (`PYTHONPATH=src pytest -q`).
- No secrets, `.env`, user media, MP3/MP4, caches or weights committed. No default auto-publish.
- `public_release_approved` stays `false`; publish approval is a separate human decision.
- CLI must keep `plan`, `run`, `validate` working exactly as before.

## Review Focus

Inputs and conditions the spec implies but no happy-path test covers, most likely to bite:

1. A programme whose last block is an aggregate `联播快讯` with several stories glued together → must not be one candidate, and no character may be lost while splitting.
2. A story repeated in two places (e.g. a 快评 or a follow-up restating a lead story) → must cluster, never be selected twice.
3. Fewer than `top_k` candidates clearing the threshold → must report insufficiency, never pad.
4. An LLM answer with an out-of-range, missing or non-numeric score, or an unknown dimension → must fail closed, not coerce silently.
5. A script that mentions a number, or an unselected story's wording, not present in the selected source → must be rejected before rendering.

---

### Task 1: Editorial data contracts and configuration

**Files:**
- Create: `src/news_video_pipeline/editorial/__init__.py`, `src/news_video_pipeline/editorial/models.py`
- Modify: `src/news_video_pipeline/default.yaml`, `src/news_video_pipeline/config.py`
- Create: `config/editorial.yaml`
- Test: `tests/test_editorial_models.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION = 1`; `SourceSpan(start:int, end:int)`; `StoryCandidate` (fields `story_id, headline, source_id, source_spans, source_text, block_index, section, entities, topic, event_time, core_facts, new_information, uncertainties, source_status, split_status, cluster_id, duplicate_of`, `to_dict()/from_dict()`); `DIMENSIONS: tuple[str,...]`; `StoryRating(story_id, scores: dict[str,int], reasons: dict[str,str], weighted_total: float, topic: str, confidence: float, flags: tuple[str,...])`; `Claim(claim_id, story_id, kind, text, source_spans, depends_on, reasoning, limitation)`; `AnalysisBrief`; `EditorialSelection`; `EditorialScript`.
- Produces: `config.load_config()` returns an `editorial` section: `mode, top_k, min_candidates, shortlist, min_total_score, min_confidence, max_topic_share, aggregate_headings, weights (8 keys = 100), critique_min, max_revisions`.

- [ ] Step 1: failing tests — `StoryCandidate.to_dict()/from_dict()` round-trips (including `source_spans` as ints); `weights` must sum to 100 or `load_config` raises `ValueError`; `editorial.top_k` must be `>= min_candidates`; unknown dimension key in `weights` raises.
- [ ] Step 2: run and see them fail (`pytest tests/test_editorial_models.py -v`).
- [ ] Step 3: implement the dataclasses (frozen where the existing `Scene` is frozen, `to_dict` mirroring `Scene.to_dict`) and the `config.py` validations.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 2: Deterministic story extraction with source spans

**Files:**
- Create: `src/news_video_pipeline/editorial/extractor.py`
- Test: `tests/test_editorial_extractor.py`

**Interfaces:**
- Consumes: `StoryCandidate`, `SourceSpan` from Task 1; `planner.sentences`, `planner.normalize_text`.
- Produces: `split_blocks(body: str) -> list[Block]` where `Block(heading, text, start, end, section, is_aggregate)`; `extract_candidates(body: str, title: str, cfg: dict) -> tuple[list[StoryCandidate], dict]` (report has `candidates, blocks, aggregate_blocks, uncertain_blocks, duplicate_clusters`); `cluster_key(headline: str) -> str`; `dedupe(candidates) -> list[StoryCandidate]` setting `cluster_id`/`duplicate_of`.

Rules: a block is a heading line followed by its body; `【…】` prefixes are kept in the heading; a heading whose name is in `editorial.aggregate_headings` is `is_aggregate`; every candidate's `source_spans` are exact offsets into `body` and `"".join(body[s.start:s.end] for s in spans) == candidate.source_text`; no story text may be lost across candidates (union length test).

- [ ] Step 1: failing tests — real `outputs/news/xinwenlianbo-20261116.md`-style fixture: block count, aggregate detection for both 快讯 headings, span exactness, `story_id` stability, and a duplicate cluster (a 快评 restating a lead story) collapsing to one `duplicate_of`.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement `split_blocks`, `cluster_key`, `dedupe`, `extract_candidates`.
- [ ] Step 4: tests pass; `PYTHONPATH=src pytest -q` still green.
- [ ] Step 5: commit.

### Task 3: Aggregate-block sub-splitting that cannot lose text

**Files:**
- Modify: `src/news_video_pipeline/editorial/extractor.py`
- Test: `tests/test_editorial_aggregate.py`

**Interfaces:**
- Produces: `split_aggregate(block: Block, cfg: dict, llm) -> list[Block]`; `verify_verbatim(block_text: str, pieces: list[str]) -> list[tuple[int,int]]` (raises `ValueError` unless the concatenated pieces equal the block text exactly, after whitespace normalisation); `llm` is a callable `(stage: str, payload: dict) -> dict` injected so tests use a fake.

A block whose split cannot be verified is returned whole with `split_status="uncertain"`; text is never dropped and no story is invented.

- [ ] Step 1: failing tests — a glued 快讯 block from the real 2026-11-14 manuscript splits into its 5 stories with all characters preserved; a fake LLM that returns paraphrased (non-verbatim) spans → `uncertain`, block kept whole, and a `ValueError` is *not* swallowed into data loss; a fake LLM returning spans in the wrong order → `uncertain`.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement `verify_verbatim` then `split_aggregate`.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 4: LLM stage helper (bounded, schema-checked, cached)

**Files:**
- Create: `src/news_video_pipeline/editorial/llm.py`
- Test: `tests/test_editorial_llm.py`

**Interfaces:**
- Consumes: `planner._openai_client`, `planner.collect_stream`, `planner.hard_deadline`.
- Produces: `class EditorialLLM` with `__call__(stage: str, payload: dict) -> dict`, `call_count`, `stage_log: list[dict]` (per stage: `model, request_count, latency_s, error, retries, content_sha256, cache_hit`); `json_object(answer: str) -> dict`; module-level `require_keys(obj, keys, stage)`.

Every stage: streaming, `max_total_s`, `reasoning_effort` from config, JSON parse, required-key check, and a per-(stage,payload-hash) on-disk cache under `<out>/.cache/editorial/`. Failures never return a partial dict.

- [ ] Step 1: failing tests — a fake client returning JSON is parsed; non-JSON answer raises `ValueError` naming the stage; a missing required key raises; the same payload twice hits the cache (client called once) with `cache_hit=True` in `stage_log`; token/latency fields recorded.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement `EditorialLLM` on top of the existing planner helpers.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 5: Weighted ranking with explainable per-dimension reasons

**Files:**
- Create: `src/news_video_pipeline/editorial/ranking.py`
- Test: `tests/test_editorial_ranking.py`

**Interfaces:**
- Consumes: `DIMENSIONS`, `StoryRating`, `StoryCandidate`, `EditorialLLM`.
- Produces: `features(candidate) -> dict`; `weighted_total(scores: dict[str,int], weights: dict[str,int]) -> float`; `validate_scores(scores: dict, stage: str) -> dict[str,int]`; `rate_candidates(candidates, cfg, llm) -> list[StoryRating]` (grouped into batches of `editorial.batch_size`, one call per batch); `ranked_table(ratings) -> list[dict]`.

`validate_scores` rejects non-integer, out-of-`0..10`, missing or unknown dimensions → `ValueError` (never coerce, never silently default). `weighted_total` is pure Python: `sum(score[d]/10*weight[d])` over the 8 dimensions.

- [ ] Step 1: failing tests — total of all-10 scores is 100.0 and all-0 is 0.0; a scale of 11/`"7"`/missing key/unknown key each raise; ordering by `weighted_total` is stable and ties break by block order; a fake LLM rating 2 candidates produces 2 `StoryRating`s with reasons for every dimension.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 6: Two-stage selection with a complete audit trail

**Files:**
- Create: `src/news_video_pipeline/editorial/selection.py`
- Test: `tests/test_editorial_selection.py`

**Interfaces:**
- Consumes: `StoryRating`, `StoryCandidate`, `EditorialSelection`, `EditorialLLM`.
- Produces: `shortlist(ratings, size) -> list[StoryRating]`; `compare(shortlist, candidates, cfg, llm) -> dict[str, dict]` (per-story `adjusted_total`, `comparison_note`, `duplicate_of`, `evidence_gap`); `select(candidates, ratings, cfg, llm) -> EditorialSelection` with `selected: tuple[str,...]`, `rejected: tuple[dict,...]` (`story_id, total, reason, duplicate, low_novelty, weak_evidence`), `insufficient: bool`, `selection_config`.

Hard rules: never select more than `top_k`; never select a `duplicate_of`; never select below `min_total_score` or `min_confidence`; if fewer than `min_candidates` qualify set `insufficient=True` and select only the qualifying ones; topic diversity is a soft constraint applied only while candidates remain above threshold.

- [ ] Step 1: failing tests — top-k enforced against an LLM that returns more; a duplicate is never selected; below-threshold candidates are recorded as rejected with a reason; insufficient case returns `insufficient=True` and no padding; a single-topic day is allowed to exceed `max_topic_share` only when nothing else qualifies; every candidate appears exactly once in `selected`/`rejected`.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 7: Analysis briefs and FACT / INFERENCE / OPINION / UNKNOWN claims

**Files:**
- Create: `src/news_video_pipeline/editorial/evidence.py`, `src/news_video_pipeline/editorial/insight.py`
- Test: `tests/test_editorial_evidence.py`, `tests/test_editorial_insight.py`

**Interfaces:**
- Consumes: `Claim`, `AnalysisBrief`, `StoryCandidate`, `EditorialLLM`.
- Produces (evidence): `validate_claims(claims: list[Claim], candidate: StoryCandidate) -> dict` (counts per kind + `anchored` ratio); `claim_from_llm(raw, story_id, candidate) -> Claim`; `assert_claims_supported(claims, candidate) -> dict`.
- Produces (insight): `build_briefs(selected_ids, candidates, cfg, llm) -> list[AnalysisBrief]`; `AnalysisBrief` carries `angle, mechanisms, second_order, counterpoints, watch_indicators, claims, uncertainty`.

Validation rules: `kind` ∈ {FACT, INFERENCE, OPINION, UNKNOWN}; every claim must cite at least one span inside the *selected* candidate; every numeric token in a `FACT` claim must occur in its cited span; a `FACT` must be lexically anchored (normalised overlap ≥ `editorial.fact_anchor_min`); `INFERENCE` must list `depends_on` ids that exist and are `FACT`; `UNKNOWN` must not contain a numeric not in source; invented numbers anywhere → `ValueError`.

- [ ] Step 1: failing tests — a fabricated number in a FACT claim is rejected; an `INFERENCE` with a dangling `depends_on` is rejected; an unanchored FACT (paraphrase far from the span) is rejected; a claim citing a span outside the selected candidate is rejected; a valid brief yields counts per kind and an `anchored` ratio of 1.0.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement `evidence.py`, then `insight.py`.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 8: Editorial script, scene contract and the critic gate

**Files:**
- Create: `src/news_video_pipeline/editorial/scripting.py`, `src/news_video_pipeline/editorial/critique.py`
- Test: `tests/test_editorial_scripting.py`

**Interfaces:**
- Consumes: `AnalysisBrief`, `EditorialSelection`, `EditorialScript`, `Scene`, `planner.pack_narration`, `planner.title_from`, `planner.TITLE_LIMIT`.
- Produces: `build_script(briefs, selection, cfg, llm) -> EditorialScript` (`title, opening_hook, sections, closing_synthesis, body`); `script_to_scenes(script, cfg) -> list[Scene]` (section → `Scene(s)` with `source_id=story_id`, every scene honouring `max_chars_per_scene` via `pack_narration`); `assert_selection_grounded(script, selected_candidates, cfg) -> dict`; `critique(script, selection, cfg, llm) -> dict` and `critique_gate(report, cfg) -> None` (raises with the failing dimensions); `revise_script(script, report, cfg, llm) -> EditorialScript` limited to `editorial.max_revisions`.

`assert_selection_grounded` enforces Layer 3: no numeric token in the narration that is absent from the union of selected `source_text`; no unselected candidate's distinctive phrasing (its headline n-grams) may appear in the narration; every `FACT` claim still anchored.

- [ ] Step 1: failing tests — a script mentioning an invented figure raises; a script naming an unselected story's headline raises; a valid script produces scenes within the slide contract with stable ids and `source_id` set; a critic report below `critique_min` raises with the dimension names; revision stops at `max_revisions` and then fails rather than looping.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 9: Pipeline integration and artifact chain

**Files:**
- Modify: `src/news_video_pipeline/pipeline.py`, `src/news_video_pipeline/quality.py`
- Test: `tests/test_editorial_pipeline.py`

**Interfaces:**
- Produces: `pipeline.run(..., editorial: str = "none", top_k: int | None = None)`; curated mode writes `news_items.json, editorial_ranking.json, editorial_selection.json, analysis_briefs.json, claims.json, editorial_script.md` before `scenes.json`, and all of them join the manifest; `quality.validate_outputs(..., editorial_artifacts: bool = False)` requires them when set.

- [ ] Step 1: failing tests — curated mode with a fake LLM writes all six artifacts and hashes them into the manifest; `validate_existing` on a curated run returns `editorial` counts; a curated run missing `analysis_briefs.json` fails QA; whole-manuscript mode output is byte-identical in structure to before (no editorial artifacts).
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement.
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 10: CLI surface

**Files:**
- Modify: `src/news_video_pipeline/cli.py`
- Test: `tests/test_editorial_cli.py`

**Interfaces:**
- Produces: `news-video editorial extract|rank|select|script --input … [--top-k N] [--config …] [--out …]`, and `run/plan` gain `--editorial {none,curated-analysis}` and `--top-k N`. Each editorial subcommand prints the artifact it wrote and performs only that stage.

- [ ] Step 1: failing tests — `extract` on a fixture prints `news_items.json` with the candidate count and exit code 0; `select --top-k 3` never prints more than 3; `run --editorial none` keeps the old code path (no `news_items.json`); an unknown mode exits non-zero with a clear message.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: implement the argparse changes (keeping the existing `run/plan/validate` flags intact).
- [ ] Step 4: tests pass.
- [ ] Step 5: commit.

### Task 11: Two professional Skills, discoverable by Pi

**Files:**
- Create: `skills/news-story-selection/{SKILL.md,scripts/evaluate_selection.py,references/newsworthiness-rubric.md,references/editorial-selection-contract.md,assets/ranking-config.example.json,assets/selection-report.example.json}`
- Create: `skills/news-insight-analysis/{SKILL.md,scripts/validate_analysis.py,references/analysis-methodology.md,references/fact-inference-opinion.md,references/editorial-quality-rubric.md,assets/analysis-brief.example.json,assets/script-outline.example.json}`
- Create: `.agents/skills/<id>/SKILL.md`, `.claude/skills/<id>/SKILL.md`
- Modify: `scripts/validate_skills.py` (nine → eleven)
- Test: `tests/test_agent_assets.py`

**Interfaces:**
- Produces: 11 canonical skills; both new scripts run against a real `editorial_selection.json` / `analysis_briefs.json` and exit 0; every backticked repo path in the new documents resolves.

- [ ] Step 1: failing tests — `validate_skills.py` reports `{'skills': 11, ...}`; the two catalog entries exist in the wrapper layer; each new script runs on a real artifact fixture and exits 0.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: write the skills (each with all three resource folders) and the wrappers; update the count.
- [ ] Step 4: `python scripts/validate_skills.py` passes; tests pass.
- [ ] Step 5: commit.

### Task 12: Curator and Analyst roles across all four platforms

**Files:**
- Create: `agents/news-curator.md`, `agents/news-analyst.md` and the four adapters each: `.pi/prompts/<name>.md`, `.codex/agents/<name>.toml`, `.claude/agents/<name>.md`, `.opencode/agents/<name>.md`
- Modify: `scripts/validate_skills.py` (role list), `docs/agent-skills.md`
- Test: `tests/test_agent_assets.py`

**Interfaces:**
- Produces: 7 role contracts, each present in all five locations, with no unresolvable referenced path; News Producer's contract additionally points at the curated-analysis entrypoint.

- [ ] Step 1: failing tests — the role list has 7 entries; all five adapter paths exist per role.
- [ ] Step 2: run and see them fail.
- [ ] Step 3: write the contracts, copying the existing adapter conventions (including `.codex/*.toml`).
- [ ] Step 4: `validate_skills.py` + tests pass.
- [ ] Step 5: commit.

### Task 13: Real acceptance on three 新闻联播 programmes, then docs and PR

**Files:**
- Create: `docs/architecture/editorial-intelligence.md`, `docs/verification/editorial-selection-e2e.md`, `docs/verification/editorial-quality-review.md`, `docs/editorial-annotation-template.md`
- Modify: `README.md`, `docs/roadmap.md`, `docs/architecture.md`, `docs/deployment.md`
- Artifacts: `outputs/editorial-<date>-<runid>/…`

**Interfaces:**
- Consumes: everything above, real manuscripts `outputs/news/xinwenlianbo-2026{1114,1115,1116}.md`, real gateway model, real espeak TTS.

- [ ] Step 1: `news-video editorial extract` on all three programmes; record candidate counts and the 快讯 split results.
- [ ] Step 2: `editorial rank` + `select --top-k 5`; record the full ranking, the Top-10 with per-dimension scores, the chosen stories and every rejection reason.
- [ ] Step 3: `editorial script`; record the briefs, claim kinds, the script, and the Layer-3 guard results.
- [ ] Step 4: full `run --editorial curated-analysis` to MP4 for at least one programme; check PPTX/PNG/SRT/timeline/QA and the duration against the 6–10 minute target.
- [ ] Step 5: regression — whole-manuscript mode on `examples/sample_news.md` still passes; `pytest -q`, `validate_skills.py`, `check_environment.py --strict`, `smoke_test.py --tier all-offline`, `news-video validate` on every output.
- [ ] Step 6: write the three documents honestly (separating unit tests / selection quality / fact verification / video QA / publish authorisation); mark anything not run as `not_run`; do not fabricate Precision@5 without human labels.
- [ ] Step 7: commit on the dev branch, push, open a PR, watch CI, do not merge.
