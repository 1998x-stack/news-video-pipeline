---
name: news-pipeline-orchestration
description: Plan and execute the local news-video CLI pipeline with idempotent artifacts, cache and failure-closed stages; use for project automation.
---

# 统一编排｜news-pipeline-orchestration

## 何时使用
当用户需要统一编排能力、优化对应工程模块或核对产物时使用；先阅读 `references/orchestration-runbook.md`，需要执行前先检查 `assets/job-spec.example.json`。

## 对应实际代码
`src/news_video_pipeline/cli.py,pipeline.py,config.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：输入文件、配置文件、目标目录、可选 --force
- 输出：可重放 output run_id、manifest、qa_report；失败诊断目录

## 标准执行流程
1. 先通过 plan 预览场景和输入限制；确保依赖 ffmpeg/ffprobe、Noto 中文字体、TTS 已可用。
2. 以内容+配置+版本哈希建立 run_id；同一 run id 上锁，成功且哈希有效则复用。
3. 运行 render PPTX/PNG → per-sentence TTS → timeline/SRT → FFmpeg → QA，然后原子提交目标目录。
4. 失败时保留 .building-* 诊断目录并中止；不能把未完成目录当作成功产物。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-pipeline-orchestration/scripts/run_pipeline.py --input examples/sample_news.md --out outputs --plan-only
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 默认无自动采集或发布行为；--force 应明确由操作者指定。
- 当前使用 POSIX fcntl，不保证原生 Windows 下直接运行。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
不是 DAG 粒度恢复/调度器；定时采集及外部发布还在后续路线图。

## 资源
- `references/orchestration-runbook.md`：细化契约、错误场景、检查点与回退策略
- `scripts/run_pipeline.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/job-spec.example.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
