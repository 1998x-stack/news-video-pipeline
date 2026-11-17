---
name: news-timeline-subtitles
description: Audit sample-accurate Scene/Cue timelines and SRT caption synchronization to narration; use when fixing subtitle drift, timing or slide mapping.
---

# 统一时间线与字幕｜news-timeline-subtitles

## 何时使用
当用户需要统一时间线与字幕能力、优化对应工程模块或核对产物时使用；先阅读 `references/timeline-invariants.md`，需要执行前先检查 `assets/timeline-contract.json`。

## 对应实际代码
`src/news_video_pipeline/timeline.py,models.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：Scene[]、每句 WAV 的 sample count、sample_rate
- 输出：timeline.json (scene/slide/cue)；subtitles/zh.srt

## 标准执行流程
1. 明确唯一时间源为 PCM WAV samples，不允许使用 MP3 长度或推测语速。
2. 逐句计算 start/end sample，再由 sample_rate 转为毫秒；暂停采样不进入字幕文字显示。
3. 每段 Scene 从前一段的 end_ms 无缝衔接，scene slide_index 自 1 开始。
4. 每个 Cue 必须严格为正时长、不重叠、位于所属 Scene 内，并与 SRT 条目数相同。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-timeline-subtitles/scripts/audit_timeline.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 末尾 Scene end_ms 必须等于 duration_ms；duration_samples / sample_rate 应与真实 WAV 时长一致。
- 不同毫秒四舍五入边界要通过测试，不应局部累加已四舍五入的毫秒。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
没有词级/字级高亮强制对齐；Whisper 只做可选转写复检。

## 资源
- `references/timeline-invariants.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_timeline.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/timeline-contract.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
