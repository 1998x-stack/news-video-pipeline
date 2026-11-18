# Editorial quality review — separating five different verdicts

The point of this document is that the following are **not** the same claim, and each
gets its own verdict. Evidence for the numbers is in
`docs/verification/editorial-selection-e2e.md`.

| Verdict | Result | Basis |
|---|---|---|
| 1. Code unit tests pass | **PASS** | 189 editorial tests + the pre-existing suite; full suite green (`PYTHONPATH=src pytest -q`) |
| 2. News **selection** quality meets the bar | **PARTIAL** | Deterministic rules hold (top_k, no duplicates, every drop explained, no padding). Ranking is defensible but unvalidated against humans |
| 3. Analysis facts were verified | **PARTIAL (machine-checked only)** | Every FACT is a verbatim excerpt with all its numbers present in the cited span; every INFERENCE has declared FACT dependencies. Semantic entailment is **not** machine-checked |
| 4. Video technical quality passes | **PASS** | 23 scenes, 47 cues, 675,248 ms audio == video (0 ms drift), 39 hashed assets, `qa_passed`, manifest re-verified by `news-video validate` |
| 5. Public release is authorised | **NOT GRANTED** | `public_release_approved: false`; fact/rights/platform approval is a human decision |

## What the system demonstrably does

- **Extracts every independent story**: 18/21/24 candidates from three real
  programmes, with 29 briefs recovered from glued `联播快讯` paragraphs and 0
  characters lost.
- **Deliberately drops most of the programme**: 13/16/19 candidates rejected, each
  with a machine-readable reason, and the final video narrates only the 5 selected.
- **Explains its picks**: a per-dimension score *and* a reason for all seven
  dimensions for all 63 candidates across the three programmes.
- **Analyses rather than restates**: every brief carries a mechanism explanation, a
  second-order consequence explicitly marked as inference, a counterpoint, watch
  indicators, and what the source does not say.
- **Refuses to overreach**: `UNKNOWN` claims outnumber `OPINION` claims by 9:5 on
  2026-11-14, and the closing synthesis states that no single trend can be confirmed
  from the day's stories.

## What the critic actually caught (2026-11-14, verbatim excerpts)

The critic produced 10–12 specific problems per draft, e.g.:

- "story_013 解说中…'19座、300公里每小时、400公里航程的参数组合，指向短途支线或区域
  航空市场，避开与干线客机直接竞争'中的'避开与干线客机直接竞争'是分析者推断，原文未
  提及竞争定位。"
- "closing_synthesis 中'关键系统的可靠性、准入节奏和承诺的可执行性，正在同时成为公共
  讨论的焦点'将五条不同领域新闻强行归纳为同一主题…叙事连贯性依赖分析者主观串联。"

These are the right complaints. They are recorded in `editorial_report.json`
(`critic.problems`) and do **not** block the run as long as the rubric and length
gates pass. That is deliberate — the critic is a reviewer with a voice, not a veto by
keyword — but it means a published script can still contain inferences a strict reader
disagrees with.

## Honest weaknesses

1. **Fluency vs. verifiability.** Requiring FACT text to be a verbatim source excerpt
   makes the arithmetic in the script dense and source-like. That is a real trade-off,
   not an oversight: the alternative is a paraphrase that no automated check can
   distinguish from an invention.
2. **Length.** The delivered video is 11.25 minutes against a stated 6–10 minute
   target. The gate and the mechanism are honest (budget → bounded revision → fail),
   the target is not yet met at this voice rate.
3. **Inference labelling is prompt-level.** The model usually writes "推论是…", but a
   reader can still find sentences where a conclusion reads as fact; the critic flagged
   exactly those and they were kept.
4. **Selection is unvalidated.** No human-labelled "correct top 5" exists, so no
   Precision@5 is claimed. The annotation template is provided for the next round.
5. **Weights are a hypothesis.** 25/20/15/15/10/10/5 has no reader study behind it.
6. **One intermittent failure.** A `rank` call can exhaust its retries on a formatting
   slip; the fix is more retries, and it was observed once in three runs.

## What a human must still do

Read `editorial_selection.json` (agree with the drops?), check each FACT against
`source.txt`, decide whether the inferences are fair, confirm rights for any material
and the platform decision. The pipeline never performs those steps and never sets
`public_release_approved`.
