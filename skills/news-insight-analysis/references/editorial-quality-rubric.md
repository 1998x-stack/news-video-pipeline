# 解读质量评审：七个维度与阈值

## 1. 定位和真相来源

- 对应契约：`src/news_video_pipeline/editorial/models.py` 的 `CRITIQUE_DIMENSIONS`（恰好七个）
- 阈值配置：`editorial.critique_min`（每个维度 0–10 的整数下限），由 `config.validate_editorial` 校验必须覆盖全部七个维度
- 提示契约：`src/news_video_pipeline/editorial/llm.py` 的 `critique` 阶段（要求给出具体可验证的问题，不得提出新观点）
- 已实现边界：评审是模型自检加人工复核，不构成事实核验，也不构成发布批准

## 2. 七个维度（恰好七个，不允许增删）

| 维度 | 含义 | 6 分的样子 | 低分信号 |
|---|---|---|---|
| factual_grounding | 是否出现原文之外的事实 | 所有事实可回到原文 span | 出现原文没有的数字、日期、机构 |
| analytical_depth | 是否解释了机制而非复述 | 讲清因果链与推动者 | 按时间顺序重述事件 |
| original_insight | 观点是否有依据且非空话 | 判断可被后续信号检验 | “意义重大”“深远影响” |
| clarity | 普通观众能否听懂 | 单句可朗读、无术语堆积 | 长句嵌套、代词指代不清 |
| audience_utility | 看完是否获得可复用认知 | 给出可带走的判断框架 | 只有情绪刺激或复述 |
| uncertainty_handling | 是否把推论当事实 | 推论有措辞标记与失效条件 | 用“必然”“已经证明” |
| narrative_coherence | 是否形成连贯叙事 | 各节有功能、转场有理由 | 新闻列表式罗列 |

评分是 0–10 的整数，写进 `critique.scores`；同时必须给出 `problems` 数组，每项指向**具体句子或具体位置**。没有具体问题的评语视为无效。

## 3. 阈值的处理

- 阈值来自配置 `editorial.critique_min`，不是代码常量；示例值见本 Skill 的 `assets/script-outline.example.json` 的 `critique.thresholds` 块与 `skills/news-story-selection/assets/ranking-config.example.json` 的 `editorial.critique_min` 块。
- 评审报告（`src/news_video_pipeline/editorial/critique.py`）输出 `scores` / `problems` / `failed` / `thresholds` 四个键；`failed` 非空则必须修订，修订循环由 `editorial.max_revisions` 上限封顶。
- 任一维度低于阈值即触发修订，修订次数上限为 `editorial.max_revisions`；超限失败。
- **不得为了“让产物通过”调低 `critique_min`**：与调低 `planner.min_source_coverage` 一样，这属于伪造质量结论，而不是修复问题。

## 4. 不合格样例（应打回）

| 问题 | 打回理由 |
|---|---|
| 开场写“大家好，今天我们来聊聊……” | clarity / audience_utility：没有信息量，浪费开场 |
| “专家认为形势依然复杂”而无原文依据 | factual_grounding + uncertainty_handling |
| 把二阶影响写成已经发生 | uncertainty_handling |
| 结语强行总结出“三大趋势” | narrative_coherence + factual_grounding（原文无此联系） |
| 提到未入选新闻作为对比 | 违反选区不变量，直接失败 |

## 5. 验收门禁

- [ ] 七个维度全部打分，分值为 0–10 整数，并给出具体问题清单
- [ ] 每个维度达到 `editorial.critique_min`
- [ ] 解说稿只涉及入选新闻；推论有措辞标记；无原文之外的事实
- [ ] 修订过程留痕（旧版本可对比），超限失败而不是降阈值
- [ ] 结论明确区分“技术通过”与“人工内容审核通过”；`public_release_approved` 始终为 false

## 6. 失败处理

1. 维度不达标：按 `max_revisions` 上限修订，每轮都重跑评审并保留结果。
2. 出现原文之外的事实：整段重写，并从 brief 的 claims 中移除无依据断言。
3. 提到未入选新闻：立刻失败并回到选区结果核对，不得只删掉那一句。
4. 评审与叙述冲突时，以原文与 claims 为依据，不以“看起来更好”为准。

## 7. 推荐调用

```bash
python skills/news-insight-analysis/scripts/validate_analysis.py outputs/<actual-output-directory>/analysis_briefs.json
```

详见 `references/analysis-methodology.md`、`docs/architecture.md` 与根目录 `AGENTS.md`。
