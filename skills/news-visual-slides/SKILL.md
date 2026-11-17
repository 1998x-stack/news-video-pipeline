---
name: news-visual-slides
description: Design and verify editable news PowerPoint slides and matching PNG video frames from a shared Scene model; use when working on layouts or slide regressions.
---

# PPTX / PNG｜news-visual-slides

## 何时使用
当用户需要PPTX / PNG能力、优化对应工程模块或核对产物时使用；先阅读 `references/layout-acceptance.md`，需要执行前先检查 `assets/design-tokens.json`。

## 对应实际代码
`src/news_video_pipeline/slides.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：Scene[]、标题、render.width/height/font_path、中文字体
- 输出：presentation/daily.pptx；presentation/slides/slide_NNN.png

## 标准执行流程
1. 同一 Scene 驱动 PPTX 原生可编辑文本和 PIL PNG 画面，不能将 PPTX 简化为截图。
2. 优先检查字形支持、2 行标题/7 行正文限制、页脚遮挡和页码。
3. 根据 scenes 数量逐一校验 PPTX slide 数与 PNG 数；视频以 PNG 为像素画面源。
4. 排版修改前后运行端到端回归并记录渲染环境、字体与尺寸。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-visual-slides/scripts/audit_slides.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- PPTX 与 PNG 内容应逻辑一致，但不同排版引擎不保证像素级相同。
- 超出版面时报错而不是裁剪文字。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
当前固定 16:9 静态幻灯片，无 9:16 自动布局、动画或语义可视化引擎。

## 资源
- `references/layout-acceptance.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_slides.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/design-tokens.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
