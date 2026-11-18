# Editorial Intelligence (curated-analysis) — Design

**Status:** approved for implementation (operator instructed "现在开始实际执行"; open questions below are recorded as implementer calls).

**Baseline:** `main` @ `139513b` (v0.1.3). Branch: `feat/editorial-intelligence-v0.2`.

## Intent

Today the pipeline is a faithful *transcription* machine: whole manuscript → `Scene[]` → PPTX/WAV/SRT/MP4.
It has no editorial judgement. A 30-minute programme becomes a 30-minute video that re-narrates
every story, including the ones with no new information.

This change adds an **AI news chief editor**: read the whole programme, identify every independent
story, rank them by value, deliberately drop the ones that do not deserve further explanation,
and produce a genuinely analytical 6–10 minute script about the 3–5 stories that matter.

Success is *not* covering the most news. Success is the highest information, judgement and
cognitive gain per minute, without clickbait, conspiracy framing, invented controversy or
emotional manipulation.

## Why now

- The media core is stable and hash-verified (v0.1.2/v0.1.3), so the editorial layer can be
  added without touching the PCM time clock, slide contract, renderer or QA gates.
- Real 新闻联播 manuscripts (2026-11-14/15/16, saved verbatim) are available locally as test
  material, and they contain the hard cases: 栏目 headings, `【…】` series, and
  `国内联播快讯`/`国际联播快讯` aggregate blocks that glue several independent stories into one
  paragraph.
- The gateway model (`iagent/standard` → `DeepSeek-V4-Flash`) is already verified for
  structured JSON with `reasoning_effort: none`.

## Goals

1. Extract every independent story candidate from a full programme with traceable source spans.
2. Rank candidates with an explainable, configurable weighted rubric (8 dimensions, 100 points).
3. Two-stage selection: cheap full-candidate pass, then a deeper comparison of the shortlist.
4. Default output 3–5 stories; never pad to reach `top_k`; never select duplicates.
5. Produce per-story analysis that answers *why it matters*, *what mechanism is at work*, and
   *what to watch next* — with FACT / INFERENCE / OPINION / UNKNOWN kept distinct.
6. Keep the existing whole-manuscript mode working, unchanged, as the default.
7. Reuse the media core untouched: `Scene[]` → slides/TTS/PCM timeline/SRT/MP4 → technical QA.

## Non-goals

- No 9:16 crop, no burned-in captions, no auto-collection/crawling, no auto-publish.
- No word-level forced alignment, no DAG-level cache.
- No multi-model orchestration: Curator/Analyst/Producer are *stages with explicit contracts*
  inside one Pi agent, not separate expensive model sessions.
- Not claiming the weights are user-validated. They are configurable initial hypotheses.

## Anti-goals (failure even if it technically works)

- Cutting the manuscript to its first five stories and calling that selection.
- Lowering `planner.min_source_coverage` to make curated output "pass".
- An unselected story's narration leaking into the final video.
- Presenting inference or editorial opinion as established fact.
- Auto-publication, or `public_release_approved = true`.

## Constraints

- `AGENTS.md`: no invented facts; single PCM clock; `Scene`/sentence contracts; fail closed;
  no silent truncation; providers replaceable; tests that need no online API must always run;
  no secrets/large artifacts committed.
- Every new output file joins the manifest hash chain.
- Schema changes bump `schema_version` *and* ship tests.
- Deterministic Python owns all arithmetic, thresholds, dedupe and range checks. The LLM
  proposes content; Python decides and verifies.

## Approaches considered

**A. Single mega-prompt on the whole programme** — one call asks for selection *and* analysis.
Cheapest. Rejected: no traceable spans, no auditable per-dimension scores, no way to test
selection independent of analysis, and one failure loses everything.

**B. Deterministic extraction + LLM editorial layer (chosen).** Rule-based story boundary
detection with exact character spans, then bounded LLM stages (understand+score → compare →
brief → script → critic), each schema-validated in Python and each independently runnable and
cached on disk. Trade-off: more moving parts, but every stage is testable offline with a fake
client, and cost is bounded and observable.

**C. Embedding-based ranking, no LLM judgement.** Fast and cheap, but "structural importance"
and "analytical depth" are not embedding-similarity problems. Rejected as the primary path;
lexical features are kept as *features for* the ranking, not as the ranking itself.

## The three grounding layers (resolving the v0.1.2 conflict)

The old `assert_source_retained()` demands that almost the whole manuscript reappears in the
narration. That is correct for whole-manuscript mode and *fatal* for curated mode, where
deliberately not covering a story is the product.

- **Layer 1 — source retention.** `source.txt` keeps the complete programme verbatim with a
  SHA-256; no input is modified or dropped. Unchanged.
- **Layer 2 — selection.** Unselected stories are dropped *by design*, and every drop is
  recorded with a reason. No global retention ratio is applied in curated mode.
  `assert_source_retained()` keeps applying to whole-manuscript/longform mode only.
- **Layer 3 — evidence for what is kept.** For selected stories only: every numeric/date token
  in the narration must exist in the cited source spans; every `FACT` claim must be lexically
  anchored in its declared span; `INFERENCE` must depend on declared `FACT` ids; and no
  unselected story's distinctive headline phrasing may appear in the narration.

`min_source_coverage` is **not** lowered anywhere. Curated mode uses the new Layer-3 rules.

## Parts decided (implementer calls, open to override)

- New package `src/news_video_pipeline/editorial/` (extractor, llm, ranking, selection, evidence,
  insight, scripting, models) — matches the repo's small-module style.
- Mode is opt-in: `--editorial none|curated-analysis` (default `none`), config section `editorial:`.
- Options are passed as explicit function parameters (not a new class) on top of the existing
  plain-`dict` config, consistent with `planner.py`.
- Aggregate blocks (`*联播快讯`) are split by an LLM proposing **verbatim spans**, which Python
  then verifies reconstruct the block exactly; on mismatch the block is kept whole and marked
  `split_status="uncertain"` rather than silently losing text.
- Weights and the critique rubric thresholds are configuration, not constants.
- Each editorial stage writes its artifact to the run directory and is reusable as its own CLI
  command, so a failed stage never forces re-paying for earlier ones.

## Left to the builder

- Exact prompt wording (must forbid invention and require verbatim spans).
- Whether the shortlist comparison is one call or one call per candidate.
- Batch sizes, given the gateway's measured 10–800 s latency variance.
