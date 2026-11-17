---
name: news-quality-gate
description: Independently audit news-video generated artifacts, hashes, technical QA and publication gating; use for CI, damaged cache and acceptance checks.
---

# 质量与归档验收｜news-quality-gate

## 何时使用
当用户需要质量与归档验收能力、优化对应工程模块或核对产物时使用；先阅读 `references/qa-matrix.md`，需要执行前先检查 `assets/qa-policy.json`。

## 对应实际代码
`src/news_video_pipeline/quality.py,pipeline.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：output directory、scenes/timeline、manifest、PPTX/PNG/WAV/SRT/MP4
- 输出：qa_report.json、manifest.json 以及可复验判定

## 标准执行流程
1. 先验证所有产物非空、Scene/PPTX/PNG 数一致、字幕条数与 Cue 数一致。
2. 比对 WAV 样本时长与 Timeline，并使用 ffprobe 检验轨道、画面尺寸和视频时长误差。
3. 验证 manifest.sha256 全部文件哈希，避免使用损坏缓存。
4. 将 qa_passed 限定为技术完整性；public_release_approved=false 和 rights_status=unverified 不得自动改写。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-quality-gate/scripts/audit_manifest.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 输出目录需包含完整 manifest，所有 manifest 路径必须局限于输出目录。
- 处理失败应显式非零退出，禁止通过生成空成功标志避开检查。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
当前 QA 未建立可审计事实证据链、音频响度标准或人工签核系统。

## 资源
- `references/qa-matrix.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_manifest.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/qa-policy.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
