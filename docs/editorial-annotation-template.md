# Editorial annotation template (for human comparison)

This round produced **no** Precision@5 or NDCG because no human labels exist. Do not
invent them. Collect them like this, one row per candidate story, then compare against
`editorial_ranking.json` and `editorial_selection.json`.

Recommended sample: three full programmes (the same ones in
`docs/verification/editorial-selection-e2e.md`), two annotators, disagreements
resolved by discussion.

## Per-candidate labels

| Field | Meaning | Allowed values |
|---|---|---|
| `story_id` | from `news_items.json` | string |
| `human_rank` | your ordering of editorial importance | 1..N, no ties (break them deliberately) |
| `should_be_selected` | would you put this in a 3–5 story episode? | `yes` / `no` |
| `reason` | one sentence, in your own words | free text |
| `category` | what makes it important | `policy` / `economy` / `diplomacy` / `technology` / `society` / `safety` / `health` / `other` |
| `new_information` | does it contain facts you did not already know? | `yes` / `no` / `unclear` |
| `analytical_potential` | is there a mechanism worth explaining? | `high` / `medium` / `low` |
| `duplicate_of` | same event as another candidate | `story_id` or empty |
| `evidence_sufficient` | can its claims be checked from the source alone? | `yes` / `no` |

## Episode-level labels

| Field | Meaning |
|---|---|
| `must_include` | candidates that a competent editor could not drop |
| `agree_with_selection` | `yes` / `partly` / `no` for the system's top-k |
| `missing_story` | a story the system dropped that should have been in |
| `weakest_selected` | the weakest story the system kept |
| `notes` | anything about tone, framing or fairness |

## Metrics to compute once labels exist

- **Precision@k** — share of the system's selected stories that an annotator marked
  `should_be_selected`.
- **Recall of `must_include`** — how many editor-mandatory stories the system selected.
- **Rank correlation** — Spearman between `human_rank` and the weighted total.
- **Drop agreement** — share of rejections where the annotator agrees with the
  recorded reason (`below_min_score` / `duplicate` / `repeat_without_progress` /
  `weak_evidence` / `below_top_k_cut`).

Report inter-annotator agreement before any of these numbers; without it a single
annotator's ranking is not evidence of selection quality.

## What NOT to record here

Do not record publication approval, rights clearance or fact confirmation in this
file. Those are separate human decisions and stay separate from editorial scoring.
