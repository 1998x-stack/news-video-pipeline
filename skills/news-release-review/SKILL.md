---
name: news-release-review
description: Prepare a human news editorial, sourcing and licensing release review without automatically approving or publishing any generated video.
---

# 发布前人工签核｜news-release-review

## 何时使用
当用户需要发布前人工签核能力、优化对应工程模块或核对产物时使用；先阅读 `references/editorial-release.md`，需要执行前先检查 `assets/human-review-template.json`。

## 对应实际代码
`src/news_video_pipeline/docs/roadmap.md,AGENTS.md`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：技术完成的视频包；内容/事实证据/授权/平台账号检查清单
- 输出：未通过时明确阻止发布；人工评估建议，不自动上传

## 标准执行流程
1. 分别确认来源、每一项核心事实、引语、图片、音色、肖像及音乐的使用权。
2. 技术验收包括 manifest、timeline、SRT、MP4 及实际声音和字幕人工试听。
3. 保留人类责任人的明确批准记录及批准对象的不可变哈希，批准不得从模型推理得出。
4. P2 发布器未实现，禁止模拟发布成功；任何平台授权和投稿需要单独显式操作。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-release-review/scripts/release_check.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 不要凭技术 QA 或文字“已核验”就把 public_release_approved 改为 true。
- 证据缺失一律待审；不生成虚构引用或许可协议。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
仅提供发布前评估脚本与核验协议，无真实审核后台或自动发布 API。

## 资源
- `references/editorial-release.md`：细化契约、错误场景、检查点与回退策略
- `scripts/release_check.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/human-review-template.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
