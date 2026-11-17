---
name: news-voice-production
description: Synthesize and inspect per-sentence Chinese narration WAV and MP3 with reproducible PCM audio timing; use when changing TTS providers or audio quality.
---

# 语音制作｜news-voice-production

## 何时使用
当用户需要语音制作能力、优化对应工程模块或核对产物时使用；先阅读 `references/audio-clock.md`，需要执行前先检查 `assets/voice-profile.example.json`。

## 对应实际代码
`src/news_video_pipeline/tts.py,timeline.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：Scene.sentences、voice.provider/rate/name/sample_rate
- 输出：单句规范化 WAV 缓存、audio/narration.wav 和 narration.mp3

## 标准执行流程
1. 为每句独立调用 TTS，规范成 mono、signed 16-bit PCM、配置采样率 WAV。
2. 以 WAV getnframes 记录每句实际采样数；句间 pause 写入静音采样。
3. 核查输出非空、格式一致、音量与长静音；音频不合格时中止，不借助估计语速补时长。
4. MP3 仅作为发行辅助文件，绝不将其编码时长当作字幕主时钟。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-voice-production/scripts/audit_audio.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- synthetic 模式输出正弦测试音，不是真实配音，必须显著标记不能发布。
- espeak 中文音色是离线测试基线；Edge 与外部 TTS 必须确认使用条款。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
当前正式适配 espeak/edge；CosyVoice、Qwen3-TTS 是路线图而非已接入能力。

## 资源
- `references/audio-clock.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_audio.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/voice-profile.example.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
