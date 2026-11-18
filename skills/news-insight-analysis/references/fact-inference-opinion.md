# 事实 / 推论 / 观点 / 未知：分类规则与常见误用

## 1. 定位和真相来源

- 对应契约：`src/news_video_pipeline/editorial/models.py` 的 `CLAIM_KINDS = ("FACT", "INFERENCE", "OPINION", "UNKNOWN")` 与 `Claim`
- 提示契约：`src/news_video_pipeline/editorial/llm.py` 的 `brief` 阶段（要求 FACT 的 quote 逐字出现、INFERENCE 的 depends_on 引用已有 FACT）
- 审计工具：`scripts/validate_analysis.py`
- 已实现边界：分类由结构校验守卫，但“这句话是否真的为真”只能由人判断；跨来源核验未实现

## 2. 四类断言的定义

| kind | 定义 | 必要依据 | 允许的措辞 |
|---|---|---|---|
| FACT | 原文明确写出的内容 | `source_spans` 非空，引语逐字来自原文 | “原文写明”“文件提到” |
| INFERENCE | 由已知事实推出来的判断 | `depends_on` 非空且指向本 brief 的 **FACT** claim；`reasoning` 与 `limitation` 非空 | “这意味着”“一种可能是” |
| OPINION | 编辑判断或价值排序 | `reasoning` 写出判断标准 | “按……的标准看”“更值得关注的是” |
| UNKNOWN | 原文无法确认的部分 | 说明缺什么信息 | “目前无法确认”“待公布” |

两条来自代码的附加约束（`src/news_video_pipeline/editorial/evidence.py`，违反即失败）：

1. **每条 claim 至少引用一个属于该条新闻的原文区间**；FACT 的区间还必须逐字支撑其文本（词面匹配率不低于 `editorial.fact_anchor_min`）。
2. 任何 claim 里出现的数字都必须出现在该条新闻的原文里；FACT 的数字还必须出现在它自己引用的那个区间内。

区间表示“这条断言谈论的来源范围”，不等于“区间中的每句话都支持它”；量化与词面守卫不是语义蕴含，内容真假仍由人判断。

## 3. 判定顺序（照这个顺序问，不要跳步）

1. 原文有没有逐字写出？有 → FACT（贴出字符区间）。没有 → 下一步。
2. 它是不是由我已经标成 FACT / 已成立的推断推出来的？是 → INFERENCE，并写出推理链与失效条件。
   `depends_on` 只能指向 FACT：推理不能架在另一条推理上，否则链条无法审计（`evidence.py` 会直接报错）。
3. 它是不是一个价值判断或优先级排序？是 → OPINION，并写出判断标准。
4. 都不是 → UNKNOWN。**不允许因为“看起来很像”就升格为 FACT。**

## 4. 常见误用（都必须打回）

| 误用 | 例子 | 处理 |
|---|---|---|
| 把推论写成事实 | “该政策必然导致投资下滑” | 改成 INFERENCE，加“一种可能是”，并写 limitation |
| 用常识补数字 | 原文未给金额，写“约数十亿元” | 删除；未提供的数据一律不得出现 |
| 把表态当结果 | “有关部门表示将整治”写成“已经整治” | 区分“表示”与“已完成”，后者需原文证据 |
| 用其他时期数据推断本次 | 引用去年同期的完成率 | 写成 UNKNOWN 或明确标注为外部信息（本仓库默认不引入外部数据） |
| 观点伪装成分析结论 | “这项规定显然更合理” | 改为 OPINION 并写出判断标准 |
| 引语跨段拼接 | 把两句不同段落的原文接成一句引用 | 拆成两条 claim，各自对应自己的 span |

## 5. 验收门禁

- [ ] 每条 claim 的 kind 都在 `CLAIM_KINDS` 内，且分类经得起上面的判定顺序
- [ ] FACT 的 span 能逐字复原引语（人工核对），数字/日期/机构/引语均来自原文
- [ ] FACT 词面锚定比例不低于 `editorial.fact_anchor_min`；claim 中的数字均能在该条新闻原文中找到
- [ ] INFERENCE 的 `depends_on` 全部指向本 brief 内的 FACT，且说明了失效条件
- [ ] OPINION 写出判断标准；UNKNOWN 没有被包装成结论
- [ ] 解说稿中推论有明确措辞标记，不出现“已经证明”“不容置疑”等表达

## 6. 失败处理

1. 发现分类错误：整条 claim 重写并保留旧版本用于对比，不得只删结论。
2. 发现无依据的数字/日期/机构：删除并记录到人工复核清单。
3. 无法判断为哪一类时：写 UNKNOWN，不要猜。
4. 修复后重跑审计脚本并保留旧结果用于差异对比；`qa_passed` 与结构化校验都不是发布批准。

## 7. 推荐调用

```bash
python skills/news-insight-analysis/scripts/validate_analysis.py outputs/<actual-output-directory>/analysis_briefs.json
```

详见 `references/analysis-methodology.md` 与根目录 `AGENTS.md`。
