# News Video Pipeline｜新闻稿 → PPT + 配音 + SRT + 时间线 + MP4

[![CI](https://github.com/1998x-stack/news-video-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/1998x-stack/news-video-pipeline/actions/workflows/ci.yml)

**状态：v0.1.0 可运行的生产内核（非无人审核发布系统）**。支持输入：新闻联播文字稿、普通新闻稿、长文章，格式为 `.txt`、`.md` 或 JSON `{ "title": "...", "body": "..." }`。

核心原则：**先生成逐句音频，以实际 PCM 采样数生成统一 timeline，所有产物均从同一个场景模型派生。** 不用 Whisper 猜测已知 TTS 句子时间戳。

## 已实现 vs 尚未实现

| 功能 | 状态 | 说明 |
|---|---|---|
| TXT / Markdown / JSON 输入 | ✅ | 单篇文章/稿件，不联网自动抓取 |
| 可重复场景规划 | ✅ | 默认规则切分，拒绝静默截断 |
| OpenAI 兼容 LLM 规划 | ✅ 可选 | 需 API；输出仍须审核事实 |
| PPTX | ✅ | 由文本形状生成、可在 PowerPoint 中编辑 |
| 每页 PNG | ✅ | 与 PPTX 共用场景数据，视频以 PNG 为画面源 |
| TTS | ✅ | espeak(-ng) 离线；可选 Edge TTS；`synthetic` 仅测试音调 |
| 时间线 + SRT | ✅ | 逐句 TTS、采样计时、页码映射 |
| WAV + MP3 | ✅ | WAV 用于合成，MP3 用于交付 |
| FFmpeg MP4 | ✅ | 16:9 静态幻灯片视频，无动画；独立质量检测 |
| 基于文件哈希的缓存和重复执行 | ✅ | 相同内容、配置与版本可以复用，支持 `--force` |
| Whisper ASR 复检 | ✅ 可选 | `faster-whisper`，需要模型下载和算力 |
| 多源事实验证、版权许可自动判断 | ❌ | 必须人工核验；后续阶段实现证据管理 |
| 9:16 重排、字幕硬烧、自动上传 | ❌ | 留待 P1/P2；不存在自动发布行为 |

## 环境要求

- Python 3.10+；FFmpeg + ffprobe；能够显示中文的 Noto CJK 字体
- 默认离线 TTS 需要 `espeak-ng`（或者 `espeak`）；中文效果偏机械，**用于闭环功能验证，不作为最终发布音质推荐**
- `edge` TTS 和 `openai-compatible` LLM 可选，需要相应网络、依赖、账号权限；不保证服务商长期可用
- Windows 原生环境需要为 `fcntl` 文件锁提供替代实现，初版支持 Linux/macOS/Docker

### 本地快速启动（Linux/macOS）

```bash
# Ubuntu/Debian 系统依赖
sudo apt-get install -y ffmpeg espeak-ng fonts-noto-cjk fontconfig
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'

# 查看分镜结果（不生成多媒体）
news-video plan --input examples/sample_news.md

# 生成完整五件套
news-video run --input examples/sample_news.md --out outputs

# 独立重新检查一个输出目录
news-video validate outputs/sample_news-<RUN_ID>

# 重新渲染（适合调试）
news-video run --input examples/sample_news.md --out outputs --force
```

macOS 可使用 Homebrew 安装 `ffmpeg`、`espeak-ng` 和 Noto 中文字体，或优先使用 Docker。

### Docker

```bash
docker build -t news-video .
mkdir -p outputs
docker run --rm \
  -v "$PWD/examples:/data:ro" \
  -v "$PWD/outputs:/outputs" \
  news-video run --input /data/sample_news.md --out /outputs
```

容器运行用户 UID 10001；如挂载目录只允许宿主账户写入，需要事先配置目录权限。

### 可选 LLM 与 Whisper

```bash
pip install -e '.[llm,whisper,edge]'
export OPENAI_API_KEY='YOUR_SECRET'
export OPENAI_MODEL='YOUR_COMPATIBLE_MODEL'
export OPENAI_BASE_URL='https://your-provider.example/v1'
news-video run --input article.md --config config/llm-whisper.yaml
```

默认仍是规则规划，完全离线可运行。`planner.provider: openai-compatible` 是可选模块；兼容端点是否支持当前 Chat Completions 参数应自行测试。**不要把敏感信息写进 YAML 或 Git 仓库。** Whisper 用于最终旁白的转写相似度检查，而非取代 TTS 已知的句子边界。

Edge 示例配置见 `config/edge.yaml`；注意 Edge TTS 非正式商业生产服务接口，使用前核查许可和使用条款。

## 输出文件

```text
outputs/<input-stem>-<content-config-version-hash>/
├── source.txt
├── scenes.json
├── timeline.json
├── manifest.json
├── qa_report.json
├── presentation/
│   ├── daily.pptx
│   └── slides/slide_001.png ...
├── audio/
│   ├── narration.wav
│   └── narration.mp3
├── subtitles/zh.srt
└── video/landscape.mp4
```

`timeline.json` 中每个 scene 有 `slide_index/start_ms/end_ms`，每句字幕有 `scene_id/start_ms/end_ms`。时长来自逐句 WAV 帧数；`qa_report.json` 检查字幕数、连续性、PPT 存在性、音频实际长度和 MP4 轨道/时长。`manifest.json` 保存生成版本、输入哈希、配置和输出文件哈希，`public_release_approved` 恒为 `false`。

`outputs/.cache/tts/` 为公共句子音频缓存。相同输入和配置会命中整体输出；如任何输出文件哈希损坏，将重新生成。

### 字幕为何不直接采用 Whisper？

对于系统自己合成的配音，每句文本和对应 WAV 已经一一对应，能知道边界的真实采样数；强制再运行 Whisper 可能反而产生识别错误。可启用 `quality.whisper_check: true` 对最终音频做**独立质量检查**。未来要求逐字/逐词高亮时，再引入强制对齐工具。

## 内容准确性与使用限制

1. 原始输入**必须由内容责任人确认事实和权利来源**。LLM 可能改写错误，首版不具备可靠自动事实核验。
2. 输入含他人受版权保护的画面、音频、文字时，请取得合法授权；本工具不从央视或抖音抓取画面。
3. `synthetic` Provider 仅输出正弦测试音，**严禁将其生成的内容作为真实配音发布**。
4. 默认没有上传或自动发布模块，验收通过仅意味着技术文件完整，并非内容合规或已审核通过。
5. 全流程允许固定环境内可重复执行/缓存，不承诺在不同系统的字体、FFmpeg、TTS 模型版本间生成完全一致的文件字节。

## 文档

- [系统架构、接口与故障边界](docs/architecture.md)
- [工程任务拆解、验收标准与阶段路线](docs/roadmap.md)
- [生产配置与部署策略](docs/deployment.md)
- [贡献与开发规则](AGENTS.md)

## 维护原则

尽量保持核心简单：单进程 CLI + 数据模型 + provider 接口 + FFmpeg。新采集器、自动发布、PPT 动画、9:16 编排、政策证据库、GPU TTS 等作为扩展插件进入，不侵入同步内核。
