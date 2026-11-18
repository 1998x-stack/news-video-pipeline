# Curated-analysis end-to-end verification (real programmes, real model, real TTS)

Everything below was measured on 2026-11-18 in this repository on macOS 27.3.0
arm64 with Python 3.12.15, `iagent` gateway model `iagent/standard`
(gateway-resolved `DeepSeek-V4-Flash`, `reasoning_effort: none`), espeak-ng 1.52.0
voice `zh` at `voice.rate 155`, ffmpeg 9.0.2.

Inputs are the verbatim 2026-11-14/15/16 新闻联播 transcripts saved under
`outputs/news/` (local only, gitignored). Nothing was trimmed before processing.

Reproduce:

```bash
export OPENAI_API_KEY=... OPENAI_BASE_URL=https://iagent.iauto.com/v1 OPENAI_MODEL=iagent/standard
news-video editorial extract --input outputs/news/xinwenlianbo-20261114.md --config config/llm.yaml --out /tmp/ed/1114
news-video editorial rank    --input outputs/news/xinwenlianbo-20261114.md --config config/llm.yaml --out /tmp/ed/1114 --show 10
news-video editorial select  --input outputs/news/xinwenlianbo-20261114.md --config config/llm.yaml --out /tmp/ed/1114 --top-k 5
news-video editorial script  --input outputs/news/xinwenlianbo-20261114.md --config config/llm.yaml --out /tmp/ed/1114 --top-k 5
news-video run --input outputs/news/xinwenlianbo-20261114.md --config config/llm.yaml \
  --editorial curated-analysis --top-k 5 --tts espeak --out /tmp/ed/1114
news-video validate /tmp/ed/1114/<run-directory>
```

## 1. Extraction

| Programme | blocks | candidates | aggregate sections | briefs split | uncertain | characters lost |
|---|---:|---:|---:|---:|---:|---:|
| 2026-11-14 | 12 | 18 | 2 | 8 | 0 | 0 |
| 2026-11-15 | 11 | 21 | 2 | 12 | 0 | 0 |
| 2026-11-16 | 17 | 24 | 2 | 9 | 0 | 0 |

`国内联播快讯` / `国际联播快讯` are containers that glue several briefs into one
paragraph. The model proposed the item texts, `verify_verbatim` proved the pieces
rebuild each container byte-for-byte, and every proposed headline was accepted only
because it occurs verbatim inside its own item. 0 of 29 briefs needed the
`uncertain` fallback. "Characters lost" is the count of non-whitespace characters in
neither a candidate span nor an explicitly reported skip record (programme name and
the two section labels are the only skip records).

## 2. Ranking — 2026-11-14 (all 18 candidates, model-judged)

Weights: public_impact 25, structural_importance 20, information_novelty 15,
analytical_depth 15, timeliness 10, evidence_quality 10, audience_utility 5.
One call per 4 candidates; 18 required 5 calls.

| # | total | topic | story_id | headline | flags |
|---:|---:|---|---|---|---|
| 1 | 78.5 | safety | story_017 | 空管通信出故障 全美航班停飞超4小时 | |
| 2 | 72.0 | technology | story_013 | 我国10吨级电动商用飞机完成首次有人驾驶智能飞行 | |
| 3 | 69.5 | health | story_011 | 2026年版国家基本医保药品目录发布 新增107种药品 | |
| 4 | 67.5 | diplomacy | story_016 | 俄称扩大乌问题谈判取决于欧洲真实意愿 | |
| 5 | 62.5 | diplomacy | story_015 | 推动亚太共同体建设迈上新台阶——国际人士期待… | |
| 6 | 60.5 | diplomacy | story_018 | 土耳其与卡塔尔签署共同防御协议 | |
| 7 | 59.0 | diplomacy | story_004 | 李强同泰国总理会谈 | |
| 8 | 58.5 | society | story_014 | 川青铁路红原2号隧道顺利贯通 | |
| 9 | 57.5 | economy | story_001 | 【建设亚太共同体 促进共同繁荣】创新亚太 携手同行 | |
| 10 | 57.0 | economy | story_007 | 政策发力显效 多项先行指标持续改善 | |
| 11 | 57.0 | economy | story_009 | 【数说APEC】APEC进口农产品丰富中国餐桌 | |
| 12 | 49.5 | diplomacy | story_008 | 2026年APEC领导人会议周活动逐步升温 | |
| 13 | 48.5 | diplomacy | story_005 | 李强会见泰国国会主席兼下议长 | |
| 14 | 48.0 | society | story_012 | 《汽车改装管理办法》公开征求意见 | |
| 15 | 44.0 | politics | story_002 | 持之以恒推进全面从严治党… | no_new_information |
| 16 | 39.5 | politics | story_006 | 【学习贯彻党的二十届五中全会精神】中央宣讲团在各地宣讲… | |
| 17 | 36.0 | safety | story_010 | 国家防总办公室安排部署2026—2027年度凌汛期防凌工作 | no_new_information |
| 18 | 30.0 | diplomacy | story_003 | 李强出席泰国总理举行的欢迎仪式 | no_new_information |

Note: the programme's lead story ranks 9th, below a US air-traffic outage and a
domestic aircraft test flight. That is the ranking behaving as intended (public
impact, novelty and analytical depth over broadcast position), not a bug.

## 3. Selection — 2026-11-14 (`--top-k 5`)

Selected: `story_017`, `story_013`, `story_011`, `story_016`, `story_018`
(five distinct topics: safety, technology, health, diplomacy, diplomacy).
`insufficient: false`. All 13 others appear in `editorial_selection.json` with a
reason: `below_top_k_cut` (6), `below_min_score` (6), `duplicate` (1 — the
"国际人士期待…" reactions item was matched to the APEC story it comments on).
No story was repeated and no duplicate cluster was selected twice.

Other programmes: 2026-11-15 → 21 candidates, selected
`story_018/story_006/story_002/story_021/story_001`, 16 rejected. 2026-11-16 → 24
candidates, top three `story_001` (83.0, 习近平在广东中山考察), `story_005` (76.0,
中俄美元首会晤), `story_003` (70.5, 《求是》文章), selected
`story_001/story_003/story_013/story_014/story_024`, 19 rejected.

## 4. Analysis — claims actually verified

2026-11-14 briefs: **14 FACT, 9 INFERENCE, 5 OPINION, 9 UNKNOWN**.

- Every FACT quotes its source verbatim; every number in a FACT occurs in the span it
  cites. During development a paraphrased FACT (0.53 lexical overlap) was rejected by
  the gate — the fix was to require a verbatim excerpt, not to lower the threshold.
- Every INFERENCE declares `depends_on` referencing existing FACT ids.
- `UNKNOWN` entries state what the source does not say, e.g. "原文没有说明故障发生的
  具体地点、涉及的具体空管中心或系统名称".

## 5. Script, length and the media artefacts

| Measure | Value |
|---|---|
| Script | 2,232 characters (budget 1,180–1,967, hard ceiling 2,262) |
| Sections | 5 (1 top + 4 supporting) + opening hook + closing synthesis |
| Scenes | 23 |
| Audio / video | 675,248 ms audio == 675,248 ms video, 0 ms drift |
| Duration | **11.25 minutes** |
| Subtitles | 47 cues, no overlap, PCM-anchored |
| Manifest | 39 hashed assets, `status: qa_passed` |
| Publication | `public_release_approved: false` |

An earlier iteration produced 3,157 characters → 961.6 s → **16.03 minutes**, and was
rejected by the length gate; the per-section character allocation replaced the global
ceiling and the model then landed at 2,232 characters. 11.25 min is still above the
10-minute upper bound: at this TTS rate the 10-minute bound needs ≤1,967 characters,
which the model did not reach within its two revisions. The gate allows at most
`max_chars × 1.15`, i.e. ~11.5 min. Landing strictly inside 6–10 min needs either a
faster voice (`voice.rate` 155 is slow for Chinese: measured 3.28 chars/s) or a
tighter hard ceiling. Neither was changed here, because lowering the ceiling without
re-measuring the voice would be guessing.

## 6. Cost and latency (real gateway)

| Stage | Result |
|---|---|
| `extract` (1 aggregate call × 2 sections) | 4.3 s |
| `rank` (18 candidates, batch 4 → 5 calls) | 43.4 s |
| `select` (shortlist 9 → 1 compare call) | 5.0 s |
| `brief` (5 calls) + `script` + `critique` | 39.5 s, 6 calls, 5 cache hits |
| Whole curated run with a warm cache | 27.1–44.9 s wall clock |

Every stage records model id, request count, latency, retries, error, content hash
and cache hit in `editorial_report.json` (`llm.stages`), together with the JSON
repairs applied.

## 7. Defects the real gateway exposed (all fixed, each with a regression test)

1. `APITimeoutError` on a 1559-character lead manuscript — the planner path, fixed in
   the previous round and inherited here.
2. Unescaped ASCII double quotes inside Chinese values break the JSON answer. Two
   unambiguous repairs (trailing comma, inner quote not followed by a value
   terminator) are applied and recorded.
3. A dimension returned as a list of strings instead of one string → the reason is now
   joined with the model's own wording; anything else is rejected.
4. An answer that fails its own schema check could not be retried, and a cached bad
   answer was permanent. Both now retry/discard within the bounded budget.
5. A model writing `depends_on: ["claim_2"]` for a claim it had labelled `c2` —
   resolved positionally.
6. Two real config bugs: `target_duration_ms` upper bound was 900,000 ms (15 min) while
   documented as 6–10 min, and the length budget did not exist at all.

Intermittent: on 2026-11-15 one `rank` invocation failed after its 2 attempts with a
missing dimension; an immediate re-run (which reused the cached good batches)
succeeded and produced a complete ranking. Raising `planner.max_retries` to 2 is the
documented mitigation for unattended runs.

## Not run in this round

- Whisper transcript re-check (`quality.whisper_check: false`, faster-whisper not installed).
- Edge TTS (dependency not installed).
- Docker build; Codex/Claude/OpenCode dynamic integration (static contracts only).
- 2026-11-17 programme (page had not been published at collection time).
- No human editorial labels exist, so no Precision@5 / NDCG is reported. The template
  for collecting them is `docs/editorial-annotation-template.md`.
