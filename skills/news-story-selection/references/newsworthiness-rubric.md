# 新闻价值评分：维度、权重与打分锚点

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/editorial/ranking.py`（`validate_scores`、`weighted_total`、`features`、`rate_candidates`）、`src/news_video_pipeline/editorial/models.py`（`DIMENSIONS`、`ScoreSet`、`StoryRating`）
- 提示契约：`src/news_video_pipeline/editorial/llm.py` 的 `rank` 与 `compare` 阶段
- 输入：整期候选新闻（story_id/headline/section/source_text）与 `editorial.weights`
- 成功产物：editorial_ranking.json 的行表（含每个维度的分数与理由）
- 已实现边界：分数来自单次模型判断加一次有界的短名单比较；跨来源事实核验、自动采集、自动发布均未实现，权重不是用户验证过的结论，选区结论始终需要人工复核

## 2. 七个维度（恰好七个，不允许增删）

| 维度 | 含义 | 观察到什么才算高分 |
|---|---|---|
| public_impact | 公共影响力 | 影响的人群规模、政策/价格/安全的实际后果，而不是题材热度 |
| structural_importance | 长期结构性重要性 | 改变制度、产业格局或长期预期的变化，而非一次性事件 |
| information_novelty | 新信息价值 | 相对一般认知真正新增的数据、决定、时间点或解释 |
| analytical_depth | 解读价值 | 存在可讲清的机制与因果链，能回答“为什么会这样” |
| timeliness | 时效性 | 与今天的时间关系：正在发生、刚公布、已有明确时间表 |
| evidence_quality | 可核实性 | 原文给出可核对的数字、机构、文件或引语 |
| audience_utility | 受众理解与注意力价值 | 看完能获得可复用的认知，而不是一次情绪刺激 |

打分是 0–10 的整数。`validate_scores` 会拒绝缺少任一维度、出现未知维度、非整数（含布尔）或越界的分值；`ScoreSet` 同样要求 `scores` 与 `reasons` 都覆盖全部七个维度，缺一个就报错——忘判一个维度不允许变成默认分。

模型还必须为每个维度写一句**基于原文**的理由。空话（“意义重大”“值得关注”）视为无效理由，应当打回重做，而不是接受。

## 3. 默认权重（合计 100，属于初始假设）

| 维度 | 默认权重 |
|---|---|
| public_impact | 25 |
| structural_importance | 20 |
| information_novelty | 15 |
| analytical_depth | 15 |
| timeliness | 10 |
| evidence_quality | 10 |
| audience_utility | 5 |

三点必须说清楚：

1. 这是**可配置的初始假设**，不是用户验证过、也不是统计校准过的权重。任何“权重已被验证”的说法都是夸大。
2. 权重是配置而不是代码常量：`config.validate_editorial` 要求 `editorial.weights` 恰好覆盖七个维度、值为非负整数且合计 100，否则 `load_config` 直接报错。
3. 修改权重会改变名次，因此必须随运行一起记入 Manifest，保证同一次结论可重放。

加权算术在 Python 里完成，不在模型里：

```
weighted_total = round(Σ (score[d] / 10 × weight[d]) for d in DIMENSIONS, 4)
```

`compare` 阶段允许给出 -15..+15 的有界修正，写入 `adjusted_total`；`effective_total` 优先取修正值。修正必须带一句引用原文的 note，不得只改数字。

## 4. 确定性特征只是特征，不是判断

`features()` 计算字符数、句子数、数字 token、`《》`机构标记、引语、日期标记，并给出 `thin_content`、`duplicate`、`uncertain_split` 标记。这些特征是廉价的证据线索，用于暴露可疑条目；它们**不是**新闻价值判断，也不能替代维度打分。

## 5. 验收门禁

- [ ] 七个维度全部打分且各有基于原文的理由，分数为 0–10 整数
- [ ] `editorial.weights` 覆盖七个维度、合计 100，且被记入 Manifest
- [ ] 排序由 Python 计算并可复现；同分时按原文 block_index 稳定排序
- [ ] `duplicate_of` 非空的条目不得进入入选名单
- [ ] 结论基于文件或可核实的调用产物；无证据时写 `unknown / manual_review_required`

## 6. 失败处理

1. 分数缺维度、越界或类型错误：立即失败并指出具体 story_id 与维度，不允许裁剪或取默认值。
2. 模型未覆盖某条候选：整批失败（`rank` 阶段要求组内每条都有评分），不允许少评一条当作通过。
3. 权重不合法：修配置，不得改代码常量绕过校验。
4. 不用“调低 `planner.min_source_coverage`”解决选题或旁白报错：该守卫约束入选旁白与原文的锚定比例，与选题阈值无关。

## 7. 推荐调用

```bash
python skills/news-story-selection/scripts/evaluate_selection.py skills/news-story-selection/assets/selection-report.example.json
```

详见 `references/editorial-selection-contract.md`、`docs/architecture.md` 与根目录 `AGENTS.md`。
