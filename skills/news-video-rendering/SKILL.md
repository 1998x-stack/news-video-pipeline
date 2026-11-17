---
name: news-video-rendering
description: Render and probe FFmpeg news video using slides and PCM-derived timeline, rejecting missing streams and duration drift; use for MP4 debugging.
---

# 视频合成｜news-video-rendering

## 何时使用
当用户需要视频合成能力、优化对应工程模块或核对产物时使用；先阅读 `references/ffmpeg-verification.md`，需要执行前先检查 `assets/render-policy.json`。

## 对应实际代码
`src/news_video_pipeline/video.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：slide_NNN.png、timeline.json、narration.wav、render FPS/尺寸
- 输出：video/landscape.mp4；ffprobe 轨道信息

## 标准执行流程
1. 生成包含精确 Scene 秒数的 ffconcat；末尾重复最后一张图像确保最后画面可显示。
2. FFmpeg fps/CFR 编码 x264 + AAC，-t 使用 total samples / sample rate。
3. 用 ffprobe 验证实际存在 video 和 audio、尺寸符合配置、格式时长差距在阈值内。
4. 删除正常临时 ffconcat，失败保留诊断信息；不得将视频存在性当作内容审核。

## 校验命令
在仓库根目录运行：
```bash
python skills/news-video-rendering/scripts/audit_video.py outputs/<run-id>
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- 避免把未转义文件路径插入 shell；当前实现已经显式拒绝单引号/换行路径。
- 允许输出帧时间量化误差，不能掩盖长时间漂移。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
仅 16:9 静态视频；不含硬字幕、动画、竖屏改排和平台上传。

## 资源
- `references/ffmpeg-verification.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_video.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/render-policy.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
