# News Video Pipeline｜新闻稿 → PPT + 配音 + SRT + 时间线 + MP4

[![CI](https://github.com/1998x-stack/news-video-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/1998x-stack/news-video-pipeline/actions/workflows/ci.yml)

**状态：v0.1.3 可运行的生产内核（非无人审核发布系统）**。支持输入：新闻联播文字稿、普通新闻稿、长文章，格式为 `.txt`、`.md` 或 JSON `{ "title": "...", "body": "..." }`。

核心原则：**先生成逐句音频，以实际 PCM 采样数生成统一 timeline，所有产物均从同一个场景模型派生。** 不用 Whisper 猜测已知 TTS 句子时间戳。

本轮本地实测（Pi + `iagent/standard` 网关）已用 2026-11-14…16 三期新闻联播真实文字稿跑通全流程，证据见 [本地部署验证报告](docs/verification/pi-deepseek-local.md)。

## 已实现 vs 尚未实现

| 功能 | 状态 | 说明 |
|---|---|---|
| TXT / Markdown / JSON 输入 | ✅ | 单篇文章/稿件，不联网自动抓取 |
| 可重复场景规划 | ✅ | 默认规则切分，拒绝静默截断 |
| 场景长度契约 | ✅ | 无论规则还是 LLM 分镜，场景/标题长度都由代码统一裁剪分组，超限报错而不是溢出幻灯片 |
| OpenAI 兼容 LLM 规划 | ✅ 可选 | 流式请求 + 可配置超时/`max_tokens`/`reasoning_effort`；输出必须通过 grounding 守卫 |
| LLM 事实守卫 | ✅ | 旁白中的数字/日期必须出现在原文，且与原文匹配率低于阈值即失败，绝不渲染凭空生成的数字 |
| PPTX | ✅ | 由文本形状生成、可在 PowerPoint 中编辑 |
| 每页 PNG | ✅ | 与 PPTX 共用场景数据，视频以 PNG 为画面源 |
| TTS | ✅ | espeak(-ng) 离线；可选 Edge TTS；`synthetic` 仅测试音调 |
| 时间线 + SRT | ✅ | 逐句 TTS、采样计时、页码映射 |
| WAV + MP3 | ✅ | WAV 用于合成，MP3 用于交付 |
| FFmpeg MP4 | ✅ | 16:9 静态幻灯片视频，无动画；独立质量检测 |
| 基于文件哈希的缓存和重复执行 | ✅ | 相同内容、配置与版本可以复用，支持 `--force` |
| 产物完整性校验 | ✅ | `news-video validate` 校验 manifest 中每个文件的 SHA-256、状态与路径安全 |
| 环境与冒烟报告 | ✅ | `scripts/check_environment.py`、`scripts/smoke_test.py` 输出可复现的 JSON 证据（密钥只报告 set/unset） |
| Whisper ASR 复检 | ✅ 可选 | `faster-whisper`，需要模型下载和算力 |
| AI 主编选题（curated-analysis） | ✅ 新增 | 从整期节目中抽取全部候选新闻（`news_items.json`）、七维度加权排名、两阶段筛选出 3–5 条并记录每条落选理由；未入选新闻不会进入成片 |
| 独立深度解读 | ✅ 新增 | 每条入选新闻生成分析简报，事实/推论/观点/未知分开，附带机制、二阶影响、反例与观察指标（`analysis_briefs.json`、`claims.json`） |
| 时长预算与内容批评 | ✅ 新增 | 由实测语速换算口播字数预算，超限退回有限次修订后失败，不靠截断满足时长 |
| 多源事实验证、版权许可自动判断 | ❌ | 必须人工核验；后续阶段实现证据管理（当前只有字面/数字级守卫，语义蕴含仍需人工） |
| 9:16 重排、字幕硬烧、自动上传 | ❌ | 留待 P1/P2；不存在自动发布行为 |

## 环境要求

- Python 3.10+（本地实测 3.12.15）；FFmpeg + ffprobe；能够显示中文的 Noto CJK 字体
- 默认离线 TTS 需要 `espeak-ng`（或者 `espeak`）；中文效果偏机械，**用于闭环功能验证，不作为最终发布音质推荐**
- 实测节奏：espeak-ng `-v zh -s 155` 约 3.3 字/秒，一篇 1.6 千字稿件约 7.7 分钟旁白，整期新闻联播（约 6.5 千字）约 33 分钟；需要更快的节奏请提高 `voice.rate`
- `edge` TTS 和 `openai-compatible` LLM 可选，需要相应网络、依赖、账号权限；不保证服务商长期可用
- Windows 原生环境需要为 `fcntl` 文件锁提供替代实现，初版支持 Linux/macOS/Docker

中文字体解析顺序：`render.font_path` → `fc-match "Noto Sans CJK SC"` → 常见 Linux Noto 路径；都找不到就报错，不会静默退化成无中文的失败产物。

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

# 整期长稿：场景数超过默认上限时提高上限，绝不截断原文
news-video run --input outputs/news/xinwenlianbo-20261114.md --config config/longform.yaml
```

macOS 可使用 Homebrew 安装 `ffmpeg`、`espeak-ng` 和 Noto 中文字体，或优先使用 Docker：

```bash
brew install ffmpeg espeak-ng fontconfig
```

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
news-video plan --input article.md --config config/llm.yaml
news-video run --input article.md --config config/llm-whisper.yaml
```

默认仍是规则规划，完全离线可运行。`planner.provider: openai-compatible` 是可选模块，**兼容端点是否支持当前参数必须实测**：

| 配置 | 默认 | 作用 |
|---|---|---|
| `planner.timeout_s` | 240 | 单次 socket 读取超时（请求是流式的，慢稿件不会因此失败） |
| `planner.max_total_s` | 900 | 一次规划调用的硬性墙钟上限，避免网络挂死 |
| `planner.max_tokens` | 8192 | **思维链与答案共用**，过小会导致只有推理没有正文 |
| `planner.max_retries` | 1 | 失败重试次数 |
| `planner.reasoning_effort` | 空 | 留空则不发送该字段；`none` 可关闭冗长思维链（本机网关实测把 1.6 千字稿件从超时降到约 40 秒） |
| `planner.min_source_coverage` | 0.75 | grounding 守卫阈值：旁白与原文的匹配率下限 |

任何返回值都必须通过 grounding 守卫：旁白中出现的数字/日期必须在原文中出现，且与原文的字符匹配率不得低于阈值，否则**整个任务失败**，不会生成待审核的半成品。这仍是启发式守卫，不能替代人工事实核验。

**不要把敏感信息写进 YAML 或 Git 仓库。** Whisper 用于最终旁白的转写相似度检查，而非取代 TTS 已知的句子边界。

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

使用 `--editorial curated-analysis` 时，同一目录额外包含（均进入 manifest 哈希链）：

```text
├── news_items.json            # 全部候选新闻 + 抽取报告（含未处理行的记录）
├── editorial_ranking.json     # 七维度分数、逐维度理由、加权总分、主题、标记
├── editorial_selection.json   # 入选 5 条 + 每条落选理由与选择配置
├── analysis_briefs.json       # 每条入选新闻的机制/二阶影响/反例/观察指标
├── claims.json                # FACT / INFERENCE / OPINION / UNKNOWN 计数与明细
├── editorial_script.md        # 经审查的口播稿（分镜由它派生）
├── editorial_report.json      # 抽取报告、批评结果、grounding 结论、LLM 成本与修复记录
└── FAILED.txt                 # 仅失败时：失败暂存目录，永不发布
```

CLI：`news-video editorial extract|rank|select|script` 可单独执行任一阶段并复用上一阶段产物（`--refresh` 强制重跑）；`run`/`plan` 支持 `--editorial` 与 `--top-k`。

`timeline.json` 中每个 scene 有 `slide_index/start_ms/end_ms`，每句字幕有 `scene_id/start_ms/end_ms`。时长来自逐句 WAV 帧数；`qa_report.json` 检查字幕数、连续性、PPT 存在性、音频实际长度和 MP4 轨道/时长。`manifest.json` 保存生成版本、输入哈希、配置和输出文件哈希，`public_release_approved` 恒为 `false`。

`news-video validate <输出目录>` 会重新计算 manifest 中每个文件的 SHA-256，并检查状态、路径是否越界；文件被改过、被删掉或 manifest 被手工改动都会明确失败。

`outputs/.cache/tts/` 为公共句子音频缓存。相同输入和配置会命中整体输出；如任何输出文件哈希损坏，将重新生成。

### 验证与可复现性

```bash
python scripts/validate_skills.py                         # 9 Skills / 5 Agents 静态校验
python scripts/check_environment.py --strict              # 环境报告（密钥只输出 set/unset）
python scripts/smoke_test.py                              # 默认只跑静态层
python scripts/smoke_test.py --tier all-offline --report outputs/local/smoke.json
python scripts/smoke_test.py --tier llm --input article.md # 付费层，必须显式指定
```

冒烟测试分层（static / offline / synthetic / tts / llm / llm-e2e / whisper），**默认永远不会触发付费或耗时检查**；缺少可选依赖时标记 `skipped` 而不是失败。

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
- [本地部署验证报告（Pi + 新闻联播实测）](docs/verification/pi-deepseek-local.md)
- [贡献与开发规则](AGENTS.md)

## 维护原则

尽量保持核心简单：单进程 CLI + 数据模型 + provider 接口 + FFmpeg。新采集器、自动发布、PPT 动画、9:16 编排、政策证据库、GPU TTS 等作为扩展插件进入，不侵入同步内核。


## Agents + Skills 跨平台扩展

本项目同时提供 **9 个专业 Skills、5 个 Agent 角色**，包含完整 references、assets 与独立诊断 scripts。支持 Pi、Codex、Claude Code、OpenCode 的各自原生入口，不修改当前新闻视频 CLI 的生产内核。

```bash
python scripts/validate_skills.py
python scripts/install_agents.py --list
python scripts/install_agents.py --platform all --target /path/to/other-project
python scripts/install_agents.py --platform pi --scope user
```

项目根目录已有可自动发现的适配入口，无需重复安装；迁移到其他项目或用户级目录使用安装脚本，默认拒绝覆盖已有不同内容的文件。完整用法参见 [多平台使用手册](docs/agent-skills.md) 和 [深度技术评审](docs/agent-integration-review.md)。


## P1.1：长稿分块与运行可靠性（v0.1.3）

可选的 `config/llm-longform.yaml` 对较长输入进行逐块 LLM 规划，分别验证 grounding、原文保留率与数字遗漏，再组合分镜；默认不开启分块。分块数量有上限，以防意外产生大量付费请求。POSIX 主线程的流式调用增加实际墙钟保护。

```bash
news-video plan --input /path/to/long-news.md --config config/llm-longform.yaml
news-video run --input examples/sample_news.md --config config/fast-preview.yaml
python scripts/prune_staging.py --out outputs --older-than-hours 24
python scripts/prune_staging.py --out outputs --older-than-hours 24 --delete
```

暂存清理默认仅预览，执行删除必须指定 `--delete`；已完成产物与活动任务不会被自动清理。快速预览配置不会改变生产默认值，**没有宣称已测得长视频加速效果**。详见 [P1.1 评审与操作指南](docs/verification/p1-longform-runtime.md)。
