# 选题契约：产物字段、硬规则与审计方法

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/editorial/models.py`（`StoryCandidate`、`StoryRating`、`EditorialSelection`）、`src/news_video_pipeline/editorial/extractor.py`（候选边界与去重）、`src/news_video_pipeline/editorial/ranking.py`（加权与排序）、`src/news_video_pipeline/editorial/selection.py`（选区硬规则与 insufficient）
- 配置校验：`src/news_video_pipeline/config.py` 的 `validate_editorial`
- 审计工具：`scripts/evaluate_selection.py`
- 已实现边界：候选来自本地节目文稿的确定性切分；不联网采集，不自动发布，不做跨来源事实核验

## 2. 三份产物的字段契约

### news_items.json

```
{"schema_version": 1, "source_id": str, "report": {...}, "items": [StoryCandidate]}
```

`StoryCandidate`：`story_id, headline, source_id, source_spans[{start,end}], source_text, block_index, section, entities, topic, event_time, core_facts, new_information, uncertainties, source_status, split_status, cluster_id, duplicate_of`。

- `source_spans` 是原文的字符偏移，`SourceSpan` 要求 `0 <= start < end`；**每条候选都必须有 span**，否则 `StoryCandidate` 直接抛错。
- `split_status ∈ {exact, llm_verified, uncertain}`：聚合块（如 `国内联播快讯`）若不能被逐字切分，就保持整体并标 `uncertain`，绝不静默丢字。
- `duplicate_of` 指向同簇的规范条目；重复条目保留自己的 id 与 span 供审计。

### editorial_ranking.json

```
{"schema_version": 1, "weights": {...}, "rows": [{"rank","story_id","headline","topic","weighted_total","adjusted_total","effective_total","confidence","flags","duplicate_of","scores","reasons","comparison_note"}]}
```

- `scores`/`reasons` 必须覆盖七个维度；`confidence` 为 0–1 浮点。
- `flags` 至少可能包含 `thin_content`、`duplicate`、`uncertain_split`、`no_new_information`。

### editorial_selection.json

```
{"schema_version": 1, "top_k": int, "selected": [story_id],
 "rejected": [{"story_id", "headline", "topic", "total", "weighted_total", "confidence",
               "duplicate", "low_novelty", "weak_evidence", "reason"}],
 "insufficient": bool, "selection_config": {...}, "notes": [...]}
```

- `reason` 是**机器可读的代码**，取自 `src/news_video_pipeline/editorial/selection.py` 的 `REASONS`：`duplicate`、`weak_evidence`、`repeat_without_progress`、`below_min_score`、`low_confidence`、`topic_share`、`below_top_k_cut`。本轮实际会写入的是 `duplicate` / `weak_evidence` / `repeat_without_progress` / `below_min_score` / `low_confidence` / `below_top_k_cut`。
- `total` 是修正后的有效总分（`effective_total`），`weighted_total` 是第一轮加权分，`confidence` 是 0–1 浮点；三个布尔标记说明落选的具体性质。
- `selection_config` 记录本次实际生效的阈值与权重（top_k / min_candidates / shortlist / min_total_score / min_confidence / max_topic_share / weights），用于回溯这一次选择到底按什么标准做的；权重改变会改变名次，所以必须随运行记入 Manifest。
- `notes` 是给人工看的字符串，例如 `insufficient: only N of the requested M ...` 或 `topic_concentration: filled the remaining slots from one topic ...`。

## 3. 硬规则（违反即失败）

| 规则 | 说明 |
|---|---|
| 不得超过 top_k | `EditorialSelection` 在 `len(selected) > top_k` 时构造失败 |
| 不得选重复 | 任何 `duplicate_of` 非空的条目不得入选，同簇只取规范条目 |
| 不得低于阈值 | 低于 `min_total_score` 或 `min_confidence` 的条目一律落选 |
| 落选必须有理由 | 每条落选写 `story_id` 与机器可读的 `reason` 代码，并带上布尔标记，而不是空话；审计脚本会把代码翻译成中文说明并列出总分 |
| 不足就如实上报 | 达标条目少于 `min_candidates` 时写 `insufficient: true`，只输出达标条目 |
| 每个候选恰好出现一次 | 全部候选要么在 `selected`，要么在 `rejected`，不允许消失 |

配置约束（`validate_editorial` 强制）：`top_k >= min_candidates >= 1`；`shortlist >= top_k`；`0 < min_confidence <= 1`；`0 < max_topic_share <= 1`；`0 <= min_total_score <= 100`；`batch_size >= 1`；`max_revisions >= 0`；`0 < fact_anchor_min <= 1`；`aggregate_headings` 为非空字符串列表；`target_duration_ms` 为 `[min_ms, max_ms]` 且 `0 < min < max`。

题材多样性（`max_topic_share`）是**软约束**：名额上限为 `max(1, round(max_topic_share × top_k))`，只在仍有达标候选可选时生效；如果因它受挡而选不满 top_k，就用同一题材补足并在 `notes` 写入 `topic_concentration` 说明，而不是交一个更短的成片。

## 4. `scripts/evaluate_selection.py` 的检查范围

只读，不修改产物。校验并打印：

- `schema_version == 1`；`top_k` 为正整数；`selected` 为非空字符串数组且长度不超过 `top_k`，无重复
- `rejected` 每条都有非空 `story_id` 与**非空 reason**；`selected`/`rejected` 不出现同一条目两次
- `total`（若存在）必须是数字；`duplicate`/`low_novelty`/`weak_evidence`（若存在）必须是布尔
- `insufficient` 必须是布尔
- 输出入选清单、落选清单（含总分、机器可读 reason 代码及其中文解释、三个布尔标记）、选区配置快照，并在 `insufficient` 为真时给出明确提示

异常输入（文件不存在、非法 JSON、字段缺失或类型错误）以非零退出码和一条明确错误结束，绝不打印“通过”。

## 5. 明确没有做的事

- **没有跨来源事实核验**：所有判断都基于用户提供的本地节目文稿，脚本不会去核实文稿本身是否真实。
- **没有自动采集**：不联网抓取新闻源，也不判断节目完整性。
- **没有自动发布**：`public_release_approved` 在现有实现始终为 false；选题结论不构成发布批准。
- **没有人工签核账本**：技术校验不等于人工签核，选区结果始终需要人复核。
- **落选不是错误**：精心挑选模式下有意不覆盖未入选新闻，这是产品定义，而不是缺陷或数据丢失。原始输入仍完整保存在 `source.txt`，未入选只是没有进入本期解说。

## 6. 失败处理

1. 先确认 `news_items.json` 的候选完整（span 可定位、id 唯一），再谈排序。
2. 权重/阈值不合法时修配置并记入 Manifest；不得改守卫阈值来“让产物通过”。
3. 出现 `insufficient: true` 时如实交付并提示人工复核，不得补足名单、不得降低 `min_total_score` 来凑数。
4. 保留旧选区结果用于差异对比；`qa_passed` 只代表技术完整性。

## 7. 推荐调用

```bash
python skills/news-story-selection/scripts/evaluate_selection.py outputs/<actual-output-directory>/editorial_selection.json
```

详见 `references/newsworthiness-rubric.md`、`docs/architecture.md` 与根目录 `AGENTS.md`。
