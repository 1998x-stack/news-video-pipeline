# 解读方法：从入选新闻到可检验的判断

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/editorial/models.py`（`AnalysisBrief`、`Claim`、`EditorialScript`）、`src/news_video_pipeline/editorial/llm.py`（`brief`、`script`、`critique` 阶段提示）
- 审计工具：`scripts/validate_analysis.py`
- 输入：editorial_selection.json 的 `selected` 与对应候选原文、标题、`editorial.critique_min` 阈值
- 成功产物：analysis_briefs.json；附带 claims.json（FACT/INFERENCE/OPINION/UNKNOWN 计数）与解说稿纲
- 已实现边界：解读是模型判断而非事实核验；跨来源事实核验、自动新闻采集、自动发布均未实现；结构化校验只证明结构合法，交付结论始终需要人工复核

## 2. 一次只讲一条新闻

解读以**单个 story_id** 为单位。跨条目的比较属于选题阶段，不在这里做。一个 brief 至少回答五个问题：

| 字段 | 必须回答的问题 | 不合格的样子 |
|---|---|---|
| angle | 这条新闻最值得讲的核心判断是什么 | “值得关注”“意义重大” |
| mechanisms | 为什么会发生、由什么推动 | 复述原文事件顺序 |
| second_order | 二阶影响是什么（必须声明是推论） | 把推测写成已经发生的后果 |
| counterpoints | 有没有替代解释；主判断在什么条件下不成立 | 只列支持自己的证据 |
| watch_indicators | 后续用什么信号可检验该判断 | “继续观察”这类无法检验的说法 |

另外必须写出 `uncertainty`：白纸黑字列出无法从原文确认的部分。`uncertainty` 为空通常意味着没有认真找过不确定性，而不是真的没有。

## 3. 主张（claims）的写法

每条 claim 是“一句话 + 认识论状态 + 依据”：

- `kind` 必须是 FACT / INFERENCE / OPINION / UNKNOWN 之一。
- `FACT`：附原文逐字引语（运行时落库为 `Claim.source_spans` 字符区间），且引语在其引用区间内的词面匹配率不得低于 `editorial.fact_anchor_min`。转述、合并两段、补全主语都不算逐字。
- `INFERENCE`：`depends_on` 必须非空，指向本 brief 内已存在的 **FACT** claim_id（推理不能架在另一条推理上）；`reasoning` 说明推理链，`limitation` 说明这条推理在什么情况下不成立。
- `OPINION`：`reasoning` 必须写出判断标准（例如“以是否改变参与者行为为标准”）。
- `UNKNOWN`：保留未知。不要为了完整而编造答案，也不要用其他时期/地区的数据顶替。

## 4. 从 brief 到解说稿

1. 开场（`opening_hook`）：10–20 秒直接讲最重要的新信号或最值得思考的问题，不做自我介绍。
2. 正文（`sections`）：每条入选新闻一节，`kind` 为 `top` 或 `supporting`；narration 是可朗读的完整句子，事实→机制→论证→转场→结论各有功能。
3. 结语（`closing_synthesis`）：只在几条新闻之间确实存在联系时点明；没有可靠联系就不强行制造大趋势。
4. 只讲入选新闻：未入选新闻的标题与特征表述不得出现，哪怕只是举反例。
5. 推论必须写成推论（“这意味着”“一种可能是”），不得说成已证实的事实。

稿纲模板见 `assets/script-outline.example.json`，字段与 `EditorialScript` 对齐，可在写稿前先做人工检查。

## 5. 验收门禁

- [ ] `kind` 四类齐全且分类正确；FACT 有非空 `source_spans`；INFERENCE 的 `depends_on` 指向存在的 FACT claim
- [ ] 每个 FACT 的引语能逐字在原文中找到，词面锚定比例不低于 `editorial.fact_anchor_min`；数字、日期、机构、引语都来自原文
- [ ] angle / mechanisms / second_order / counterpoints / watch_indicators / uncertainty 均非空且有信息量
- [ ] 明确写出主判断的失败条件
- [ ] 七个评审维度达到 `editorial.critique_min`，未达标则修订，修订次数不超过 `editorial.max_revisions`
- [ ] 无证据时写 `unknown / manual_review_required`

## 6. 失败处理

1. 缺 kind、kind 非法、FACT 缺 span、INFERENCE 缺 `depends_on` 或依赖非 FACT：整条 brief 失败，不允许跳过该条继续。
2. 引语不是逐字原文：失败并指出 claim_id；不得改成“大意如此”。
3. 评审维度不达标：按上限内修订重试；超限失败，不得调低 `critique_min` 让产物通过。
4. 不确定的事实：写 UNKNOWN 并列入人工复核清单，不做自动发布动作。

## 7. 推荐调用

```bash
python skills/news-insight-analysis/scripts/validate_analysis.py outputs/<actual-output-directory>/analysis_briefs.json
```

详见 `references/fact-inference-opinion.md`、`references/editorial-quality-rubric.md`、`docs/architecture.md` 与根目录 `AGENTS.md`。
