# 语音制作：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/tts.py,timeline.py`
- 输入契约：Scene.sentences、voice.provider/rate/name/sample_rate
- 成功产物：单句规范化 WAV 缓存、audio/narration.wav 和 narration.mp3
- 已实现边界：当前正式适配 espeak/edge；CosyVoice、Qwen3-TTS 是路线图而非已接入能力

## 2. 分阶段操作

### 1. 检查点 1
为每句独立调用 TTS，规范成 mono、signed 16-bit PCM、配置采样率 WAV。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
以 WAV getnframes 记录每句实际采样数；句间 pause 写入静音采样。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
核查输出非空、格式一致、音量与长静音；音频不合格时中止，不借助估计语速补时长。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
MP3 仅作为发行辅助文件，绝不将其编码时长当作字幕主时钟。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] synthetic 模式输出正弦测试音，不是真实配音，必须显著标记不能发布。
- [ ] espeak 中文音色是离线测试基线；Edge 与外部 TTS 必须确认使用条款。
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
python skills/news-voice-production/scripts/audit_audio.py outputs/<run-id>
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
