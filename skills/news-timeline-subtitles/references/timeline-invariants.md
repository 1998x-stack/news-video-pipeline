# 统一时间线与字幕：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/timeline.py,models.py`
- 输入契约：Scene[]、每句 WAV 的 sample count、sample_rate
- 成功产物：timeline.json (scene/slide/cue)；subtitles/zh.srt
- 已实现边界：没有词级/字级高亮强制对齐；Whisper 只做可选转写复检

## 2. 分阶段操作

### 1. 检查点 1
明确唯一时间源为 PCM WAV samples，不允许使用 MP3 长度或推测语速。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
逐句计算 start/end sample，再由 sample_rate 转为毫秒；暂停采样不进入字幕文字显示。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
每段 Scene 从前一段的 end_ms 无缝衔接，scene slide_index 自 1 开始。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
每个 Cue 必须严格为正时长、不重叠、位于所属 Scene 内，并与 SRT 条目数相同。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] 末尾 Scene end_ms 必须等于 duration_ms；duration_samples / sample_rate 应与真实 WAV 时长一致。
- [ ] 不同毫秒四舍五入边界要通过测试，不应局部累加已四舍五入的毫秒。
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
python skills/news-timeline-subtitles/scripts/audit_timeline.py outputs/<run-id>
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
