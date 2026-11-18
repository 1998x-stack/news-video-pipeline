---
name: news-insight-analysis
description: Build a per-story AnalysisBrief that separates FACT, INFERENCE, OPINION and UNKNOWN, anchors every fact in verbatim source text and states when its own judgement would fail.
---

# 解读与洞察｜news-insight-analysis

## 何时使用
当用户需要解读与洞察能力、优化对应工程模块或核对产物时使用；先阅读 `references/analysis-methodology.md` 与 `references/fact-inference-opinion.md`，需要执行前先检查 `assets/analysis-brief.example.json` 与 `assets/script-outline.example.json`。

## 对应实际代码
`src/news_video_pipeline/editorial/insight.py,evidence.py,models.py`（`AnalysisBrief` 构建、Layer-3 事实守卫与 `Claim`/`AnalysisBrief`/`EditorialScript` 契约）与 `src/news_video_pipeline/editorial/llm.py`（brief / script / critique 阶段的结构化 JSON 契约）。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：入选条目的原文与标题（news_items.json + editorial_selection.json 的 selected）、`editorial.critique_min` 阈值
- 输出：analysis_briefs.json；补充产物 claims.json（含 FACT/INFERENCE/OPINION/UNKNOWN 计数）与解说稿纲

## 标准执行流程
1. 只对**已入选**的条目做解读，一次讲清一条：angle（最值得讲的核心判断）→ mechanisms（为什么会发生）→ second_order（二阶影响，必须声明是推论）→ counterpoints（替代解释与成立条件）→ watch_indicators（后续可检验的信号）→ uncertainty。
2. 每条 claims 必须标注 kind ∈ {FACT, INFERENCE, OPINION, UNKNOWN}；FACT 必须附原文逐字引语（落库为 `Claim.source_spans`），不得转述、不得拼接不同段落。
3. INFERENCE 必须写非空 depends_on，指向本 brief 内已存在的 claim_id，并写明 reasoning 与 limitation；OPINION 必须写出判断标准；UNKNOWN 保留未知，不许编造答案。
4. 生成解说稿前后都要按 `editorial.critique_min` 的七个维度自检；任何维度不达标即修订，修订次数上限为 `editorial.max_revisions`，超限就失败而不是降低阈值。
5. 交付前明确写出“这个判断在什么条件下不成立”，并把它与 uncertainty 一起交给人工复核。

## 校验命令
在仓库根目录运行（分析简报由 script 阶段写入 `--out` 目录）：
```bash
news-video editorial script --input examples/sample_news.md --out outputs/editorial
python skills/news-insight-analysis/scripts/validate_analysis.py outputs/editorial/analysis_briefs.json
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- FACT/INFERENCE/OPINION/UNKNOWN 必须严格区分：推论、观点、猜测不得写成已确认事实（禁止“已经证明”“必然导致”这类措辞）。
- 每个 FACT 必须能回到原文的字符区间；数字、日期、机构、引语必须逐字来自原文，不得来自常识或模型记忆。
- 不得引入原文之外的事实、来源、引语或时间；无法核实的内容写 `unknown / manual_review_required`。
- 解说稿只讲已入选新闻，未入选新闻的标题与特征表述不得出现。
- 结构化校验（kind、span、depends_on）只证明结构合法，不证明内容为真；内容仍需人工复核。

## 当前实现边界
本仓库不做跨来源事实核验、自动新闻采集、自动发布，也没有人工签核账本。解读是模型判断，不是事实核验结论；FACT 的逐字引语与推论是否成立必须由人核对，结构化校验只能证明结构合法。

## 资源
- `references/analysis-methodology.md`：解读流程、各字段写法与失败条件
- `references/fact-inference-opinion.md`：四类断言的定义、判定顺序与常见误用
- `references/editorial-quality-rubric.md`：七个评审维度、阈值与不合格样例
- `scripts/validate_analysis.py`：独立诊断工具（只读，不修改分析产物）
- `assets/analysis-brief.example.json`、`assets/script-outline.example.json`：机器可读的产物与稿纲模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
