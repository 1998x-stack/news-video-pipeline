# 本地部署与深度验证报告｜Pi + DeepSeek-V4-Flash（经 iagent 网关）

本文件记录 **真实执行** 的环境、命令与产物，不包含任何 API Key、用户私人路径或新闻原文全文。
较大的音视频产物保存在被 `.gitignore` 忽略的 `outputs/` 中，本文件只提供摘要、哈希前缀与度量。

---

## 1. 运行环境摘要

| 项目 | 值 |
|---|---|
| 操作系统 | macOS 27.3.0（Darwin，arm64 / Apple Silicon） |
| CPU 架构 | arm64 |
| Python | 3.12.15（Homebrew，`/opt/homebrew/bin/python3.12`，项目 `.venv/`） |
| 包管理 | pip 26.3 + venv（系统默认 `python3` 为 3.9.6，低于 `requires-python >=3.10`，未使用） |
| Pi | 1.5.2（`/opt/homebrew/bin/pi`） |
| FFmpeg / ffprobe | 9.0.2 |
| espeak-ng | 1.52.0（本轮新装：`brew install espeak-ng`，同时带入 pcaudiolib 1.3） |
| 中文字体 | `fc-match "Noto Sans CJK SC"` → `NotoSansCJKsc-Regular.otf`（未记录用户主目录绝对路径） |
| Docker | 29.9.1（本轮未执行容器构建） |
| 磁盘可用 | 约 656 GB |
| 可选依赖 | `openai` 3.52.0 已装；`edge-tts`、`faster-whisper` **未安装**（相关层标记 skipped，未伪称已测） |

环境报告可由命令复现：`python scripts/check_environment.py --strict --out outputs/local/environment.json`。

## 2. 基线 Git Commit

| 项目 | 值 |
|---|---|
| 仓库 | `github.com/1998x-stack/news-video-pipeline` |
| 基线分支 | `main` |
| 基线 commit | `5423cc514bd0933ba2737a3fe30a1f42ac094a67` |
| 基线工作树 | 干净（`git status --short` 无输出） |
| 与远端关系 | `HEAD == origin/main`，ahead/behind = 0/0 |
| 被验证的代码状态 | 分支 `fix/planner-gateway-grounding-and-verification`，代码提交 `2b34792`（工具与文档提交在其后） |
| 版本 | 基线 0.1.1 → 本轮 0.1.2（行为变更，run_id 随之变化） |

## 3. Pi + 模型配置结果

| 项目 | 值 |
|---|---|
| Pi provider | `iagent`（`~/.pi/agent/models.json`，OpenAI-compatible，`authHeader: true`） |
| Pi 会话模型 | `iagent/standard`（本会话 `PI_MODEL`，thinking level `high`） |
| 网关返回的真实模型名 | `DeepSeek-V4-Flash`（响应体 `"model"` 字段，**证明该 ID 是供应商别名**） |
| 凭据 | 环境变量存在（报告仅输出 `set`/`unset`，不输出值/长度/前缀） |
| 连通性 | `GET /v1/models` → HTTP 200，33 ms；`POST /v1/chat/completions` → HTTP 200 |
| 工具调用 | 本报告全部内容由该模型在 Pi 会话中通过 read/bash/edit/write 工具完成（多轮工具调用可用） |
| Pipeline Planner | `planner.provider=openai-compatible`，`model=iagent/standard`，`base_url=https://iagent.iauto.com/v1`（记录在 `manifest.config.planner`） |

### 3.1 网关行为实测（直接影响可用性）

| 观测 | 证据 |
|---|---|
| 思维链与答案**共用** `max_tokens` | `max_tokens=8192` 的流式请求把全部 SSE 花在 `reasoning` 上，`finish_reason=length`，`content` 为空 |
| 思维链开销巨大 | 1.6 千字真实稿件：思维链字符数 15 970，正文 3 726，总耗时 **495.7 s** |
| 关闭思维链有效 | `reasoning_effort: "none"` → 思维链字符数 0，同一稿件 **39.6 s** 成功返回合法 JSON |
| 延迟波动极大 | 同规模调用实测 10 s / 13 s / 24 s / 39 s / 65 s / 135 s / 801 s |
| 流式会取消“总时长”兜底 | 一次调用在流式模式下挂起超过 900 s（进程仍在等数据） |

## 4. Skills / Agents 加载结果

| 项目 | 结果 |
|---|---|
| 静态校验 | `python scripts/validate_skills.py` → `{'skills': 9, 'agents': 5, 'status': 'passed'}` |
| 资源引用校验 | 新增：反引号仓库路径逐个解析，实测校验 **48 条** Skill 文档引用 + 全部 Agent 适配器引用，全部存在 |
| Pi 项目 Skill 自动发现 | 9 个全部被发现，路径为 `.agents/skills/<name>/SKILL.md`（与 Pi 官方文档支持的 Agent Skills 位置一致） |
| Pi 强制加载 Skill | `pi -p "/skill:news-input-governance …"` 与 `/skill:news-timeline-subtitles …` 均退出码 0；session JSONL 中出现 `<skill name=… location="…/.agents/skills/…/SKILL.md">` |
| Skill 内容加载方式 | Pi 注入的是 **薄入口**，其中要求再读仓库根的 `skills/<name>/SKILL.md` 与 `references/` / `assets/` / `scripts/`；这些路径真实存在（已由校验器保证） |
| Prompt 模板 | `/news-producer <参数>` 真实展开：session JSONL 中存在模板全文且 `$ARGUMENTS` 已被替换 |
| 九个 Skill 脚本可执行 | 全部在真实产物目录上执行成功（见 6.3） |
| Codex / Claude / OpenCode 动态测试 | **not_run**：本机没有这三款工具的运行环境，只做了文件格式与安装路径的静态验证（安装器测试） |

## 5. 依赖安装结果

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'      # Pillow 13.0.0, python-pptx 1.0.2, PyYAML 6.0.3, pytest 9.2.0
.venv/bin/python -m pip install -e '.[llm]'       # openai 3.52.0, pydantic 2.14.3
brew install espeak-ng                            # 1.52.0 + pcaudiolib 1.3
```

未安装 `edge-tts`、`faster-whisper`：因此 **Edge TTS 与 Whisper 复检本轮未验证**，报告中不声称已通过。
原始安装日志保存在 `outputs/local/*.log`（被忽略，未提交）。

## 6. E2E 执行记录

### 6.1 输入素材

使用 `https://cn.govopendata.com/xinwenlianbo/YYYYMMDD/` 的公开文字稿，逐字保存、未截断：

| 日期 | 栏目数 | 全文字符数 | 头条字符数 |
|---|---|---|---|
| 2026-11-14 | 12 | 6 551 | 1 559 |
| 2026-11-15 | 11 | 7 204 | 1 381 |
| 2026-11-16 | 17 | 7 066 | 1 152 |

2026-11-17 页面当时尚未更新（当日 18:29 抓取，节目 19:00 播出），因此使用最近三期已发布稿件。
抓取与正文抽取只作为**本地一次性操作**（`outputs/news/`，被忽略）：仓库按 README 明确不提供联网采集器。

### 6.2 产物矩阵（engine 0.1.2）

| 场景 | 输出目录 | 分镜 | 字幕 | 音频 ms | 视频 ms | 漂移 ms | 哈希文件数 |
|---|---|---|---|---|---|---|---|
| 11-14 头条（LLM 分镜 + espeak） | `xinwenlianbo-20261114-lead-d4b123243e74444e` | 18 | 33 | 463 057 | 463 057 | 0 | 27 |
| 11-15 头条（LLM 分镜 + espeak） | `xinwenlianbo-20261115-lead-44fcda7bfaddea41` | 16 | 37 | 420 341 | 420 360 | 19 | 25 |
| 11-16 头条（LLM 分镜 + espeak） | `xinwenlianbo-20261116-lead-947c5accb9e804a6` | 18 | 25 | 374 634 | 374 640 | 6 | 27 |
| 11-14 整期（规则分镜 + espeak） | `xinwenlianbo-20261114-bbb7944afe7cfacf` | 80 | 145 | 1 987 444 | 1 987 444 | 0 | 89 |
| 官方示例（规则分镜 + espeak） | `sample_news-d18d2dc6593288c5` | 3 | 6 | 52 460 | 52 480 | 20 | 12 |

每个目录都实际存在并检查过：`source.txt`、`scenes.json`、`timeline.json`、`manifest.json`、`qa_report.json`、`presentation/daily.pptx`、`presentation/slides/*.png`、`audio/narration.wav`、`audio/narration.mp3`、`subtitles/zh.srt`、`video/landscape.mp4`。

独立复核（全部通过）：

- PPTX：80 页（整期）为 **原生文本框/形状**，无一张图片，可在 PowerPoint 中直接编辑；标题与正文均未溢出。
- PNG：与 PPTX 同数据源，逐页 1280×720 RGB。
- WAV：单调 1 声道 / 16 bit / 24 000 Hz，整期 47 698 658 帧，与 `timeline.duration_samples` 完全一致。
- MP3：`ffmpeg` 解码正常（`libmp3lame` 192 kbps）。
- SRT：条数与 `timeline.cues` 一致，时间轴单调不重叠（`validate_timeline` + `news-video validate`）。
- MP4：h264 + aac，1280×720 @ 25 fps，整期 49 686 帧、时长 1987.440 s，与 PCM 时钟漂移 0 ms。
- Manifest：`rights_status=unverified`、`public_release_approved=false`、`input_sha256` 与输入文件一致、`source.txt` 与原文逐字一致。
- `news-video validate` 对全部 10 个输出目录返回 0（重算每个文件 SHA-256）。

音频产物哈希前缀（完整值在各自 `manifest.json` 内）：

| 输出目录 | mp4 sha256 | srt sha256 | manifest sha256 |
|---|---|---|---|
| `…1114-lead-d4b123243e74444e` | `ad3aec7b008305fc` | `1c92db3bca8df1a1` | `b1126b05d820889b` |
| `…1115-lead-44fcda7bfaddea41` | `9c403065ca56756a` | `4400d3639971775f` | `4f6c0379d7901168` |
| `…1116-lead-947c5accb9e804a6` | `70c23a36bb434ff1` | `68f170ef3ba02d6c` | `93e3f98108756e45` |
| `…1114-bbb7944afe7cfacf` | `eb4e081928619a75` | `c35e7547f25c020f` | `db8bd0127699731a` |
| `sample_news-d18d2dc6593288c5` | `0642487c3dd76d79` | `6b237f20aa6b20e7` | `444ed748dcecbcb8` |

**跨机器字节一致性不予保证**（字体、FFmpeg、espeak 版本差异都会改变输出字节）。

### 6.3 九个 Skill 脚本（对真实产物执行）

`audit_input.py`、`audit_scenes.py`、`audit_slides.py`、`audit_audio.py`、`audit_timeline.py`、`audit_video.py`、`audit_manifest.py`、`run_pipeline.py`、`release_check.py` 全部可执行；
`audit_manifest.py` 在整期产物上核对 89 个文件哈希通过；`release_check.py` 恒定返回退出码 2（不可自动发布），包括把 manifest 的 `public_release_approved` 手工改成 `true` 的情况。

### 6.4 性能与可靠性实测

| 项目 | 实测 |
|---|---|
| 相同输入二次运行（结果级缓存） | 20 万分之一秒级返回同一目录（0.207 s） |
| 输出文件被破坏后重跑 | manifest 哈希比对发现损坏并完整重建（1.98 s） |
| 句子级 TTS 缓存 | 整期 33 分钟旁白在缓存命中后拼接 < 30 s；缓存文件被破坏后会重新合成 |
| 同一 run_id 三进程并发 | 仅产生一个输出目录，三个进程均返回该目录且退出码 0（flock 生效） |
| 中途失败（注入渲染异常） | 不生成 manifest、无发布目录，仅保留带 `FAILED.txt` 的 `.building-*` 暂存目录 |
| 整期端到端 | 648 s（缓存命中，engine 0.1.2）／1071 s（首次，engine 0.1.1） |
| 语音节奏 | espeak-ng `-v zh -s 155` 约 3.3 字/秒（整期 6 551 字 → 1987 s 旁白） |

## 7. 发现的问题及修复

详见 `docs/roadmap.md` 的「v0.1.2 本地实测修复」表。摘要：

| 级别 | 问题 | 修复与验证 |
|---|---|---|
| P0 | LLM 规划在真实稿件上必然超时：硬编码 `timeout=90`，无 `max_tokens`/思维链控制，非流式 | 流式 + 四个可配置网关参数；1.6 千字稿件从 4 分 32 秒失败变为 39.6 秒成功 |
| P0 | LLM 输出没有任何事实守卫，AGENTS.md 第 1 条无代码约束 | `planner.assert_grounded()`：虚构数字/日期与低匹配率一律整体失败；三期真实稿件实测匹配率 1.000 / 1.000 / 0.979 |
| P0 | LLM 分镜不遵守场景长度契约，必现 `Text overflow on scene_001` | 两个 provider 共用 `pack_narration()`；不删字不改字，仍超 `max_scenes` 才报错 |
| P1 | `news-video validate` 不校验 manifest 哈希 | 新增 `verify_manifest()`（重算 SHA-256 + 路径越界 + 状态检查）+ 8 个回归用例 |
| P1 | 句子 TTS 缓存把引擎版本硬编码为 `0.1.0` | 改用包 `__version__`，避免修复 TTS 后复用旧音频 |
| P1 | LLM 路径报错为 `Invalid scenes array`，无场景数、无修复建议 | 报告实际场景数与 `planner.max_scenes`，明确“提高上限而非截断” |
| P1 | 缺少可复现的环境/冒烟证据链 | 新增 `scripts/check_environment.py`、`scripts/smoke_test.py`；CI 增加四层冒烟与证据上传 |

## 8. 测试结果

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src pytest -q` | **64 passed**（基线 18 → 64；新增 46 个回归用例） |
| `python scripts/validate_skills.py` | passed（含新增资源路径解析） |
| `python scripts/check_environment.py --strict` | 退出码 0 |
| `python scripts/smoke_test.py --tier all-offline` | passed 7 / failed 0 / skipped 0（static + offline + synthetic + 真实 espeak） |
| `news-video validate outputs/*` | 10/10 退出码 0 |
| `release_check.py` | 退出码 2（不可发布），行为符合预期 |

`skipped`/`not_run` 的诚实清单：Edge TTS 动态测试、Whisper ASR 复检、Docker 构建、Codex/Claude/OpenCode 动态集成、真机 CI 结果（推送后由 GitHub Actions 给出）。

## 9. 仍然未完成的能力

- 自动新闻采集、SourceEvidence/StoryClaim 证据链、版权自动核查、人工签核后台。
- 9:16 重排、转场、硬字幕、词级对齐、封面/目录页。
- 商业授权中文 TTS 与稳定批处理资源管理；当前只有 espeak（机械）与未验证的 Edge。
- 多平台 OAuth 上传、发布幂等、指标回流（**不存在任何自动发布动作**）。
- 分步骤 DAG 缓存与完整可回滚部署；失败暂存目录无自动清理（整期长稿可达 170–180 MB）。
- LLM grounding 守卫是启发式的：拦不住同义改写造成的语义漂移，也不检查中文汉字数字（如“二十届”）。

## 10. 下一阶段建议

1. **长稿分块规划**：整期稿件单次 LLM 调用极可能超过 `max_total_s=900`；应先按栏目切分再合并，并保持现有 grounding 守卫。
2. **渲染吞吐（P1-11）**：33 分钟成片需 648–1071 s；可评估 `-preset`/CRF/按静态段拼接或降低 `render.fps`。
3. **暂存目录生命周期（P1-12）**：清理策略 + 磁盘阈值告警。
4. **TTS 质量（P1-04/P1-05）**：接入已授权中文 TTS，并启用 Whisper 复检（本机尚未安装）。
5. **推 Git 后核对 CI**：本轮新增的 CI 步骤（espeak-ng 真实语音层）需要在真实 Actions 环境确认。

---

### 复现本轮验证

```bash
git checkout 2b34792   # 被测代码状态；后续提交只含工具与文档
python3.12 -m venv .venv && .venv/bin/python -m pip install -e '.[test,llm]'
brew install ffmpeg espeak-ng fontconfig
python scripts/check_environment.py --strict
PYTHONPATH=src .venv/bin/python -m pytest -q
python scripts/smoke_test.py --tier all-offline --report outputs/local/smoke.json
# 付费层（需自备凭据，默认不会执行）
export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
news-video run --input <本地稿件.md> --out outputs --config config/llm.yaml --tts espeak
```
