---
name: news-story-selection
description: Rank and select the few stories worth explaining in a Chinese news programme, with per-dimension reasons, duplicate suppression and an honest insufficiency report.
---

# 选题与排序｜news-story-selection

## 何时使用
当用户需要选题与排序能力、优化对应工程模块或核对产物时使用；先阅读 `references/newsworthiness-rubric.md` 与 `references/editorial-selection-contract.md`，需要执行前先检查 `assets/selection-report.example.json` 与 `assets/ranking-config.example.json`。

## 对应实际代码
`src/news_video_pipeline/editorial/ranking.py,selection.py,models.py`（维度校验、加权算术、选区硬规则与 `StoryRating`/`EditorialSelection` 契约）与 `src/news_video_pipeline/editorial/llm.py`（rank / compare 阶段的结构化 JSON 契约）。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：news_items.json 的候选新闻（含 story_id/source_spans/source_text）、editorial 权重与阈值配置、editorial_ranking.json
- 输出：editorial_selection.json: top_k/selected/rejected/insufficient/selection_config/notes

## 标准执行流程
1. 先通读整期节目，确认候选来自 `editorial.extract_candidates` 的 `StoryCandidate`：story_id 唯一、source_spans 能在原文中定位；缺 id、缺 span 或重复 id 立即失败。
2. 按七个维度逐条打 0–10 的整数分并写一句基于原文的理由。分数由 Python 校验：缺维度、未知维度、非整数或越界都直接报错，不允许静默取默认值。
3. 加权总分由 Python 计算（score/10×weight，权重必须恰好覆盖七个维度且合计 100）。模型不决定名次；compare 阶段只做同事件判定、重复判定与 ±15 的有界修正。
4. 落选条目逐条写下 story_id 与 reason；达标条目少于 min_candidates 时写 `insufficient: true` 并只输出达标条目，不得为凑数放宽阈值或补足名单。

## 校验命令
在仓库根目录运行（选区阶段的产物在 `--out` 目录下）：
```bash
news-video editorial select --input examples/sample_news.md --out outputs/editorial
python skills/news-story-selection/scripts/evaluate_selection.py outputs/editorial/editorial_selection.json
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- selected 不得超过 top_k；任何 `duplicate_of` 非空的条目不得入选；每个候选在 selected/rejected 中恰好出现一次，且落选必须有 reason。
- 不得通过调低 `planner.min_source_coverage` 让选题或成片“通过”：该守卫约束的是入选旁白与原文的锚定比例，与选题阈值无关，调低它只会让未核实的表述进入成片。
- 未入选条目的标题与特征表述不得出现在最终旁白里；主动落选是本模式的产品结果，不是错误。
- 权重与阈值是配置而不是代码常量；改动后必须记入 Manifest 并可重放。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
未实现：跨来源事实核验、自动新闻采集、自动发布、人工签核账本。排名分数来自一次模型判断（含一次有界的短名单比较），七个默认权重是初始假设，不是用户验证过的结论。选区结论始终要求人工复核。

## 资源
- `references/newsworthiness-rubric.md`：七个评分维度的定义、默认权重与打分锚点
- `references/editorial-selection-contract.md`：news_items / editorial_ranking / editorial_selection 的字段契约与硬规则
- `scripts/evaluate_selection.py`：独立诊断工具（只读，不修改选区产物）
- `assets/ranking-config.example.json`、`assets/selection-report.example.json`：机器可读的配置与产物模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
