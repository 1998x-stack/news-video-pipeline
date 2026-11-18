# Editorial intelligence — architecture

Status: implemented in this branch. Baseline `main` @ `139513b` (v0.1.3), branch `feat/editorial-intelligence-v0.2`.

## What problem this solves

v0.1.3 turns a manuscript into PPTX/audio/subtitles/MP4 faithfully. Fed a full
30-minute 新闻联播 transcript it produces a 30-minute video that re-narrates every
story, including the ones with no new information. The editorial layer adds the
missing judgement: read the whole programme, rank every story, deliberately drop
most of it, and explain the 3–5 that matter.

## Pipeline

```
full programme transcript (verbatim, hashed)
  ↓ extractor.py        deterministic story boundaries, exact character spans,
                        aggregate 联播快讯 splitting (LLM proposes, Python verifies)
  news_items.json       StoryCandidate[] + extraction report
  ↓ ranking.py          model scores 7 dimensions 0-10 + a reason each; Python does
                        the rubric arithmetic and the range checks
  editorial_ranking.json
  ↓ selection.py        shortlist → comparative second pass → top-k decision
  editorial_selection.json  selected + every rejection with a machine-readable reason
  ↓ insight.py          one bounded call per selected story → AnalysisBrief
  analysis_briefs.json, claims.json   FACT / INFERENCE / OPINION / UNKNOWN
  ↓ scripting.py        narration from validated briefs only
  editorial_script.md
  ↓ critique.py         rubric + length gate, bounded revision, then fail
  ↓ planner-free Scene[]  → existing slides → TTS → PCM timeline → SRT → MP4 → QA
```

Scenes are derived from the reviewer-approved script, never from the programme
again, so a dropped story cannot reappear downstream.

## Modules

| File | Responsibility |
|---|---|
| `editorial/models.py` | `schema_version 1` contracts: `StoryCandidate`, `SourceSpan`, `Claim`, `ScoreSet`, `StoryRating`, `AnalysisBrief`, `EditorialSelection`, `EditorialScript` — all JSON round-trippable |
| `editorial/extractor.py` | block segmentation with exact offsets, `【】`/栏目 handling, aggregate detection, `verify_verbatim`, duplicate clustering, `derived_headline` |
| `editorial/llm.py` | `EditorialLLM`: streaming, hard wall-clock deadline, JSON repair, per-stage key check, `check` hook with bounded retry, opt-in content-addressed cache, stage log |
| `editorial/ranking.py` | score validation, weighted total, lexical features, batch scoring |
| `editorial/selection.py` | shortlist, comparative pass, top-k with dedupe/threshold/confidence/diversity rules, full audit |
| `editorial/evidence.py` | FACT anchoring, numeric containment, `depends_on` integrity |
| `editorial/insight.py` | analysis briefs, claim id rewriting, brief-level grounding |
| `editorial/scripting.py` | script building, length budget, scene derivation, Layer-3 grounding |
| `editorial/critique.py` | rubric scoring, length gate, bounded revision |
| `pipeline.py` | `run(..., editorial=..., top_k=...)`, artifact chain, manifest |
| `quality.py` | `validate_editorial_artifacts` |

## The three grounding layers

v0.1.2's `assert_source_retained()` requires nearly the whole manuscript to reappear
in the narration. That is right for whole-manuscript mode and fatal for curated
mode, where not covering a story is the product. The layers are therefore split:

1. **Source retention** — `source.txt` keeps the programme verbatim with its
   SHA-256. Never modified. Unchanged from v0.1.3.
2. **Selection** — unselected stories are dropped deliberately, each with a recorded
   reason in `editorial_selection.json`. No global retention ratio applies here.
3. **Evidence for what is kept** — for selected stories only: every spoken number
   must exist in a selected story's source; every `FACT` must be a verbatim excerpt
   of its cited span (or, failing that, clear `editorial.fact_anchor_min`); every
   `INFERENCE` must depend on declared `FACT` claim ids; and no unselected story's
   distinctive wording may appear in the narration.

`planner.min_source_coverage` is unchanged at 0.75 and still gates whole-manuscript
mode. It is **not** relaxed anywhere for curated mode.

## Determinism boundary

Python owns: boundaries, offsets, arithmetic, thresholds, dedupe, range checks,
length budgets, retries, cache keys, and every failure decision.
The model owns: which facts to call out, the mechanism explanation, the angle, the
wording — and nothing that Python can check itself. A malformed or unsupported
answer fails the run; it is never coerced into a plausible one.

## Known limits

- Layer-3 checks are lexical and numeric. Semantic entailment is not machine-checked;
  the critic flags unsupported inferences but a human still has to judge them.
- The rubric weights (25/20/15/15/10/10/5) are configurable initial hypotheses, not
  validated against reader studies.
- Curated mode needs the LLM; only `extract` degrades gracefully without a key
  (aggregate items become `uncertain` containers).
- Whole-episode LLM planning cost scales with candidate count; `batch_size` and
  `shortlist` bound it, and a re-run reuses the content-addressed cache.


## Review hardening (PR #11 follow-up)

- FACT 的代码门禁现在要求 claim.text 与所引 source span 逐字等价（仅忽略标点与空白），不得把相似度 0.6 当作语义蕴含或引用证明。
- 每条已入选新闻的独立解说段落数字必须存在于该条新闻原文，不能跨已入选新闻借用数字。
- 6–10 分钟上限不再乘以 1.15 宽容系数；口播文本超过预算会进入有限修订循环并失败。真实 PCM 时间线在 FFmpeg 前和最终 QA 时都要通过严格目标时长检查。原先 11.25 分钟的报告仍不算达标，下一轮需用真实 TTS 重跑。

- FACT 引用的规范化只忽略空白和有限的中文句读符号；正负号、百分号和小数点会保留，避免把 -5.2% 与 5.2% 当成相同事实。

- `news-video validate <run-dir>` 现在默认使用 Manifest 中记录的实际生产配置，而非当前机器的默认配置；只有显式传入 `--config` 才覆盖校验配置。这对自定义时长窗口、语音和帧率尤为重要。


## Optional review policy (current iteration)

**Time is a quality target, not a censorship gate.** The pipeline first attempts bounded revisions toward 6–10 minutes, then `duration_policy: warn` preserves the information and records `within_target | under_target | over_target` plus real PCM deviation in QA/Manifest. `duration_policy: strict` explicitly opts into refusal. Media stream integrity, fact quotes, numerical attribution, selected-story scope and human approval are unchanged hard checks.

**Semantic assessment is not verification.** `semantic_review_mode: 'off'` is the default and performs no extra LLM calls. `report` performs one bounded, content-addressed review request per selected story, validates the list of known claim IDs and verbatim evidence quotes, stores `semantic_review.json` and retains `human_review_required=true`. `strict` blocks FACT/INFERENCE claims rated contradicted or insufficient by the reviewing model; use it only after calibrating model reliability. The reviewer can make mistakes and shares its source limitations with the generator.

**Human selection quality** uses independent, blinded 0–3 relevance and binary inclusion labels, then computes metrics from both annotators separately with disagreement reporting. No label means no computed metrics; see the evaluation runbook.
