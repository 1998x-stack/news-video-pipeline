# 任务拆解与验收路线

## P0 完整生产内核（首版已实现）

| ID | 任务 | 验收标准 | 状态 |
|---|---|---|---|
| P0-01 | 规范化新闻/文章输入 | TXT/MD/JSON，空输入/非法类型明确报错 | ✅ |
| P0-02 | 规则和可选 LLM 分镜 | 单个输入变成稳定 `Scene[]`；超限报错 | ✅ |
| P0-03 | PPTX + PNG | 每个 Scene 对应一页，含中文与页码 | ✅ |
| P0-04 | TTS Provider | 逐句 WAV mono PCM，可替换参数 | ✅ |
| P0-05 | 同步引擎 | WAV 采样数推导场景与字幕时戳，单调、不重叠 | ✅ |
| P0-06 | MP3 + SRT | 存在有效音轨和 SRT，时长来自同一 timeline | ✅ |
| P0-07 | FFmpeg 视频 | 16:9 MP4，音轨有效，无累积漂移 | ✅ |
| P0-08 | 质量门禁 | 独立 ffprobe/WAV/SRT 检查，失败不提交结果 | ✅ |
| P0-09 | 可重复执行 | 相同内容和配置复用，文件哈希校验 | ✅ |
| P0-10 | 本地测试 + CI + Docker | 规则测试 + 合成音频端到端测试 | ✅ |

## v0.1.2 本地实测修复（基于 2026-11-14…16 真实新闻联播稿件）

| Issue | 级别 | 问题 | 修复 | 回归测试 |
|---|---|---|---|---|
| P0-1 | 阻断 | 旧 `llm_plan` 硬编码 `timeout=90` 且不支持 `max_tokens`/思维链控制，真实 1.6 千字稿件必现 `APITimeoutError`（实测 4 分 32 秒后失败；开启思维链时需 495 秒） | 流式请求 + `timeout_s`/`max_total_s`/`max_tokens`/`max_retries`/`reasoning_effort` 可配置；实测 39.6 秒成功 | `test_llm_plan_accepts_valid_json_and_sends_gateway_controls`、`test_llm_plan_reports_reasoning_only_response`、`test_collect_stream_enforces_a_wall_clock_deadline` |
| P0-2 | 阻断 | LLM 路径完全不做事实守卫，AGENTS.md 第 1 条“不得增添数字/日期”没有代码约束 | `assert_grounded()`：数字/日期必须出现在原文，且与原文字符匹配率不得低于 `min_source_coverage`，否则整个任务失败 | `test_invented_number_is_rejected`、`test_wholesale_invention_is_rejected_by_coverage`、`test_llm_plan_fails_closed_on_invented_fact` |
| P0-3 | 阻断 | LLM 路径不遵守场景长度契约，真实稿件必现 `ValueError: Text overflow on scene_001`，而报错却建议改动仅对规则规划生效的 `max_chars_per_scene` | 两个 provider 共用 `pack_narration()`：超长句在中文分句处切开，再按上限分组；不删字不改字；仍超 `max_scenes` 则报错 | `test_llm_scenes_are_regrouped_to_the_slide_contract`、`test_heuristic_plan_splits_a_single_overlong_sentence` |
| P1-1 | 稳定性 | `news-video validate` 只检查文件存在与格式，不校验 manifest 哈希，改过的产物也能“验证通过” | 新增 `verify_manifest()`：重算 SHA-256、检查状态与路径越界 | `tests/test_quality.py`（8 个用例） |
| P1-2 | 正确性 | 句子级 TTS 缓存哈希把引擎版本硬编码为 `0.1.0`，包版本已到 0.1.1，修复 TTS 后会静默复用旧音频 | 改用包 `__version__` | `tests/test_e2e.py::test_validate_existing_verifies_hashes_and_rebuilds_tampered_output`（重建验证） |
| P1-3 | 可用性 | LLM 路径报错信息为 `Invalid scenes array`，没有场景数也没有修复建议 | 改为报告实际场景数与 `planner.max_scenes`，并明确“提高上限而不是截断” | `test_llm_plan_rejects_scene_overflow_without_truncating`（已更新断言） |
| P1-4 | 完整性 | `validate_outputs` 的必需文件清单缺少 `source.txt`/`scenes.json` | 加入必检清单 | 现有 E2E 覆盖 |
| P1-5 | 工程效率 | 缺少可复现的环境/冒烟报告，无法逐轮对照 | 新增 `scripts/check_environment.py`、`scripts/smoke_test.py`（分层 + 密钥脱敏）；CI 增加静态/离线/合成/真实语音四层 | `tests/test_tooling.py`（7 个用例） |

**仍未修复（已记录）**：最后一句之后的 `pause_ms` 静音、失败暂存目录无自动清理、完整低层模型思维链开销、网关延迟波动（实测同规模调用 10–800 秒）。

## P1 生产可靠性与内容审核

| ID | 工作项 | 具体交付 / 判定条件 |
|---|---|---|
| P1-01 | Scene JSON Schema + Pydantic 校验 | 每个字段、字数、引用 ID 有校验与版本迁移（**部分完成**：长度契约与 grounding 已由代码强制，尚缺 schema 版本迁移） |
| P1-02 | Source Evidence 和引语证明 | 新闻每个核心事实能够定位原始段落 |
| P1-03 | DAG 缓存与细粒度恢复 | 单段 TTS 失败只重试该段，固定工具/模型版本 |
| P1-04 | TTS 专业中文语音 | 云端正式授权 TTS 或本地 CosyVoice/Qwen3-TTS，记录版权与音色 |
| P1-05 | ASR 语音质量 | 对照转写差异、数字、专有名词并能给出复检报告 |
| P1-06 | 页面排版与视觉回归 | 图片对比、字形完整、标题溢出检查（**部分完成**：已有溢出硬门禁与长度契约，尚缺图像级回归对比） |
| P1-07 | 独立时间线中间格式 | 同步 `Scene, Cue, Transition` + 语速/转场与 BGM 元数据 |
| P1-08 | 可视化人工审批 | 讲稿校对/证据签核/预览/版本回溯 |
| P1-09 | 更强校验 | 各 slide 画面切换误差、音量/LUFS、静音、重复字幕检测（**部分完成**：已加 manifest 哈希与路径安全校验） |
| P1-10 | 失败告警 | 成本、耗时、错误分类及重试策略看板 |
| P1-11 | 渲染吞吐 | 33 分钟成片需约 11–18 分钟编码（49 686 帧）；可用 `-preset`/CRF/`render.fps` 或按静态段拼接优化 |
| P1-12 | 暂存目录生命周期 | 失败或被中止的运行会留下 `.building-*`（整期长稿 170–180 MB），需清理策略与磁盘阈值 |
| P1-13 | 长稿 LLM 预算 | 整期稿件的单次规划调用极可能超过 `planner.max_total_s=900`；需要章节切分或分块规划 |

## P2 全渠道制作与出版

| ID | 工作项 | 具体交付 / 判定条件 |
|---|---|---|
| P2-01 | 9:16 重新排版 | 横/竖版使用同一内容数据，支持单事件短视频 |
| P2-02 | 图表与封面设计系统 | 模板参数、原创素材、版权元数据与版式测试 |
| P2-03 | 高亮字幕/动画 | 词级对齐（强制对齐模型），与转场严格共享时钟 |
| P2-04 | B站/抖音/YouTube 出版适配 | 权限核验、用户审核后投稿、投稿ID和重试幂等 |
| P2-05 | 排程及数据源采集 | 20:00 北京时间启动，轮询与节目源 completeness gate |
| P2-06 | 内容追踪 | 更新视频复核；政策后续变化与旧文章关联 |

## Definition of Done（新增功能的统一门槛）

每项代码变更必须包含：配置样例、最小可运行示例、确定性的单元测试、必要的集成测试、明确的故障行为和边界文档。任何涉及 AI 输出或外部新闻内容的功能，应有 provenance、未验证状态和人工审核出口。任何发布功能都不得默认开启。


## v0.1.3 后续状态

- P1-11 **部分交付**：配置可选 H.264 preset、CRF、超时和 12 FPS 快速预览；正式 33 分钟性能 Benchmark 及 VFR 轨道门禁未完成。
- P1-12 **手动清理工具已实现**：`prune_staging.py` 默认 dry-run，显式删除需符合年龄/路径/运行锁门禁；自动清理策略、配额告警尚未实现。
- P1-13 **可选长稿分块已实现**：按原文切块、请求数量上限、逐块事实字面/保留率守卫、全球 Scene 限制与 POSIX 主线程超时；模型真稿重测、结构化证据核验仍需后续迭代。

## Editorial intelligence（AI 主编与深度解读，本分支实现）

真实数据：用 2026-11-14/15/16 三期新闻联播原稿，`iagent/standard`（网关解析为 DeepSeek-V4-Flash）+ 离线 espeak 完整跑通，证据见
`docs/verification/editorial-selection-e2e.md`、`docs/verification/editorial-quality-review.md`、`docs/architecture/editorial-intelligence.md`。

已交付：候选新闻抽取与联播快讯拆条（29 条简讯，0 字丢失）、七维度可配置加权排名、两阶段筛选与完整落选审计、事实/推论/观点/未知分离的分析简报、由审查稿派生分镜的完整媒体链。

明确未交付：

- **时长尚未落入 6–10 分钟**：实测 11.25 分钟（语速 3.28 字/秒）；门槛与机制已实现，目标本身未达成。
- **分析质量未与人工标注对比**：没有人工标签，因此不给出 Precision@5；标注模板见 `docs/editorial-annotation-template.md`。
- **语义蕴含仍未校验**：只有字面/数字级守卫；批评者会指出越界推论，但不会否决成片。
- **排名维度 10–10 分制**：模型偶尔漏一个维度或返回数组，已有有限重试与修复；某次 rank 用尽 2 次尝试仍失败，重跑（命中缓存）成功。
- 权重 25/20/15/15/10/10/5 是初始假设，未经读者研究验证。


## v0.2 质量迭代（2026-11-18）

- 编辑时长从默认阻断改为软目标（`duration_policy: warn`），可选严格模式。技术 QA 记录真实 PCM 时长和目标偏差，**不承诺实测 6–10 分钟已达标**。
- 引入双人盲标注模板与评测 CLI：Precision@k、NDCG@k、must-include recall、Cohen kappa、disagreement。未收集人工标签，因此用户样本评价仍为 NOT RUN。
- 引入可选的语义风险二次评估（off/report/strict），输出严格结构化的逐 Claim 证据引用与审查状态。即使模型判定 supported，仍需人工核验新闻事实与权利；当前无独立外部证据源或付费网关实测。
- 后续：真实新闻联播三期以上的 curated 完整媒体回归、二人独立标注至少十期、语义审查对抗样本和多模型验证。
