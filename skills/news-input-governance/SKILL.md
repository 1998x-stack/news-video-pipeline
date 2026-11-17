---
name: news-input-governance
description: Validate and audit news manuscripts, source provenance, rights and editorial assumptions before making video; use for TXT, Markdown or JSON input review.
---

# 输入与证据｜news-input-governance

## 何时使用
当用户需要输入与证据能力、优化对应工程模块或核对产物时使用；先阅读 `references/source-provenance.md`，需要执行前先检查 `assets/review-checklist.json`。

## 对应实际代码
`src/news_video_pipeline/planner.py:read_input`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：原稿 UTF-8 TXT/MD/JSON；来源 URL（可选）；人工权利信息（不可自动推定）
- 输出：标题/字数/输入哈希/警告；未核实事实与权利清单

## 标准执行流程
1. 先核对文件扩展名、UTF-8 编码、3 MB 上限以及 JSON body 是否存在；原样保存输入哈希。
2. 提取可识别标题并记录来源 URL、采集时间、发行主体；未知值必须写 unknown。
3. 将逐项事实与文字证据分开登记；对政策、日期、数量、引语标记需要人工核验。
4. 对版权、肖像、授权保留待审状态。技术处理不得产生发布批准。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-input-governance/scripts/audit_input.py examples/sample_news.md
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 不得联网假设输入来源权威；也不能补写未提供的新闻事实。
- 绝不因为缺少授权证明就默认为已获授权。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
P0 仅支持用户本地输入，不提供自动联网采集、引用验证或版权许可裁定。

## 资源
- `references/source-provenance.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_input.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/review-checklist.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
