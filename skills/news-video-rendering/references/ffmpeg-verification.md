# 视频合成：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/video.py`
- 输入契约：slide_NNN.png、timeline.json、narration.wav、render FPS/尺寸
- 成功产物：video/landscape.mp4；ffprobe 轨道信息
- 已实现边界：仅 16:9 静态视频；不含硬字幕、动画、竖屏改排和平台上传

## 2. 分阶段操作

### 1. 检查点 1
生成包含精确 Scene 秒数的 ffconcat；末尾重复最后一张图像确保最后画面可显示。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
FFmpeg fps/CFR 编码 x264 + AAC，-t 使用 total samples / sample rate。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
用 ffprobe 验证实际存在 video 和 audio、尺寸符合配置、格式时长差距在阈值内。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
删除正常临时 ffconcat，失败保留诊断信息；不得将视频存在性当作内容审核。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] 避免把未转义文件路径插入 shell；当前实现已经显式拒绝单引号/换行路径。
- [ ] 允许输出帧时间量化误差，不能掩盖长时间漂移。
- [ ] 所有结论从文件或可核实的调用产物得出；若无证据，写 `unknown / manual_review_required`
- [ ] 输入、配置、工具版本、时间戳与产物哈希可供重放
- [ ] 回归测试可运行，新增逻辑具有非法输入、边界输入与正常输入测试

## 4. 失败处理

1. 不运行媒体管线后续阶段，先确认上游输入与契约。
2. 记录错误类型、输入路径、对应 Scene/Cue 或文件名（不要记录密钥）。
3. 如果是外部服务或许可不明确，不得自动回退为伪造内容、其他版权素材或 synthetic 配音。
4. 修复后重新执行校验，保留旧结果用于差异比对；不得把 `qa_passed` 等同于 `public_release_approved`。

## 5. 推荐调用

```bash
python skills/news-video-rendering/scripts/audit_video.py outputs/<run-id>
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
