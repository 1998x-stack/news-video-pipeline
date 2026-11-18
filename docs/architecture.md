# 体系架构与技术决策

## 输入契约

输入为 `UTF-8` 文本，扩展名 `.md` / `.txt` / `.json`。JSON 必须含 `body` 字符串，可选 `title`。Markdown 首行 `# ...` 视为标题，其他段落为正文。单文件最多 3 MB；不自动联网搜索或下载新闻。

## 核心数据流

```mermaid
flowchart TD
 A[Text / Markdown / JSON] --> B[Input Validation]
 B --> C[Planner: heuristic / LLM]
 C --> D[scenes.json]
 D --> E[Editable PPTX + PNG]
 D --> F[Per-sentence TTS → PCM WAV]
 F --> G[Audio concatenator]
 G --> H[timeline.json]
 H --> I[SRT]
 H --> J[FFmpeg renderer]
 E --> J
 G --> J
 J --> K[MP4]
 K --> L[QA/Manifest]
 I --> L
 E --> L
 L --> M{Publish approval?}
 M -- Not in MVP --> N[Human review required]
```

### 不变量

1. `scene.id` 全局唯一；场景排序决定 `slide_index`，从 1 开始。
2. `timeline.scenes` 严格连续，首场景从 0 开始，末场景结束时间等于总 WAV 实际时长（毫秒四舍五入）。
3. 字幕必须单调、互不重叠，并位于其所属场景时间范围内；句尾休止时间不分配给字幕。
4. WAV 固定 mono / signed 16-bit PCM / 配置采样率，记录 `duration_samples` 防止浮点累积误差。
5. 视频总时长与音频时长误差不得超过可配置阈值；FFmpeg CFR 画面边界允许约 1 帧量化。
6. 任一步失败都不生成状态为 `qa_passed` 的发布包；必须成功完成质量验收后原子切换目录。
7. 本地文件由绝对内容哈希记录；对相同输入、配置和代码版本优先复用，无需重复调用 TTS/LLM。
8. **场景长度契约属于代码，不属于模型**：任何 provider 输出的 Scene 都必须满足 `len(body) <= planner.max_chars_per_scene`、标题不超 `TITLE_LIMIT`；超出时按句子/分句边界重新分组，不删字也不改字，仍超 `max_scenes` 则报错。
9. **LLM 旁白必须可追溯**：数字/日期必须出现在原文中，且旁白与原文的字符匹配率不得低于 `planner.min_source_coverage`，否则整个任务失败。
10. `news-video validate` 必须重算 manifest 中每个文件的 SHA-256 并检查路径是否越界；不能仅凭 `status` 字段判定产物完整。

### 场景长度契约的实现

`planner.pack_narration()` 是规则规划与 LLM 规划共用的同一个函数：先在中文逗号/分号/顿号处切分超长句，再贪心按上限分组。因此幻灯片溢出只可能来自渲染器与契约之间的漂移，而 `slides.render_slides` 仍保留最终溢出报错作为第二道门。

## 缓存与可恢复性

`run_id=SHA256(raw_input_bytes + canonical_config + source_url + engine_version)[0:16]`。同一 `run_id` 加 POSIX 文件锁以避免同一输出目录同时写入。TTS 句子缓存使用文本+语音配置+引擎版本的独立哈希；引擎版本直接取包版本，避免修复 TTS 后仍然复用旧音频。完成的输出目录带有 Manifest 哈希，可验证完整性后直接复用；损坏则重算。构建中使用 `.building-*` 临时目录，失败后保留 `FAILED.txt` 供排查。

**实测收益**：整期新闻联播（80 场景 / 1987 秒旁白）在句子缓存命中后，TTS+拼接耗时不到 30 秒；未命中时需要逐句调用 espeak 与 ffmpeg 归一化。

**已确认的运维缺口**：失败或被杀掉的运行会留下 `.building-*` 目录（整期长稿可达 170–180 MB），当前无自动清理。生产环境应加磁盘阈值告警与定期归档。

**范围说明**：这是 v0.1 的「结果级跳过 + TTS 句子缓存」，尚不是分步骤缓存恢复。后续应引入 `StageArtifact` DAG，满足 LLM/素材/布局粒度的缓存并对工具、字体、模型二进制做版本锁定。

## Provider 设计与建议接口

- `Planner`: `plan(title, source_text) -> Scene[]`，默认可复现规则规划；可选 OpenAI-compatible Chat Completions 接口（流式 + 可配置超时/预算 + grounding 守卫）。两类 provider 必须产出同一个 Scene 契约，包括场景长度上限。
- `TTS`: `synthesize(sentence, voice_config) -> mono PCM WAV`；当前 espeak(-ng)、Edge；将来可加入 CosyVoice/Qwen3-TTS/Piper。
- `ASRQuality`: `check(wav, expected_text) -> similarity`；目前 faster-whisper 只在显式启用时加载；模型下载需联网。
- `Renderer`: PPTX 原生形状和 PIL PNG 都由 `Scene` 驱动；FFmpeg 合成 MP4；未来替换为 HTML/Canvas/Remotion 引擎也不修改 timeline 契约。
- `Publisher`: 当前没有实现；未来必须将平台鉴权/审查/投稿/查询状态做成独立模块。

## 已知性能特征

| 阶段 | 实测 | 说明 |
|---|---|---|
| 规则分镜 | < 0.1 s | 80 场景整期长稿 |
| LLM 分镜（本机网关，关闭思维链） | 10 s – 800 s | 同一路线的真实调用波动极大；开启思维链时同一篇 1.6 千字稿件需 495 s 且可能只有推理没有正文 |
| espeak 逐句 TTS | 1.6 千字约 10 s（冷缓存） | 语音节奏约 3.3 字/秒 |
| 音频拼接 + SRT | < 1 s（缓存命中） | 直接用采样数推导；整期 33 分钟旁白拼接 < 30 s |
| FFmpeg 合成 720p25 | 整期 33.1 分钟成片（49 686 帧）耗时 648–1071 s | 静态幻灯片仍需生成全部 25 fps 帧 |
| PPTX + PNG | 80 页约 5 s | PIL 绘制原生形状 |

因此整期长稿的主要成本在语音时长、视频帧数与外部 LLM 延迟，而不是文本处理；提高 `voice.rate`、降低 `render.fps` 或改用分块规划是最直接的三个调节点。

## 已知设计取舍

- PPTX 文字可编辑，但当前 PIL 视频幻灯片与 Office 渲染不是像素级一致（字体/排版器差异），视频以 PNG 为准。
- 规则规划按句和段切分，不保证复杂新闻语义和摘要质量；LLM 规划只是内容草稿，必须经人工审核。
- 默认 espeak 中文音色受限，推荐实际制作使用有授权的中文 TTS 服务；不能因技术 QA 通过就视为内容可发布。
- 当前仅 16:9，未生成封面页/目录页、词级字幕、动画、竖版重排或发布者上传逻辑。

## 未来事实核验设计

单独增加 `SourceEvidence`，包含 `source_id, url, published_at, retrieved_at, quote_spans, rights_status, hash`，`StoryClaim` 关联证据和有效期。LLM 的任何分析结论应包含 `fact/inference/unknown` 标记，涉及政策与统计的数字强制二次比对，不能把无来源结果自动提交为真。


## v0.1.3 的范围

可选原文分块 LLM 模式为每次调用添加独立字面输入保留与数字遗漏门禁，整体完成时还会全局复检；不等价于语义事实认证。POSIX 主线程采用 SIGALRM 防止长时间流阻塞；非 POSIX/后台线程不支持这一调用模式。结果缓存复用独立 `verify_manifest` 校验。失败暂存不自动清理，运维可用 `scripts/prune_staging.py` 显式处理。视频默认 CFR 不变；预览模式仅调整 fps/preset/CRF。详见 [P1.1 说明](verification/p1-longform-runtime.md)。
