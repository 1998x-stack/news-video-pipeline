# 新闻视频 Skills / Agents：跨平台使用手册

## 目标与实际范围

该层不替换当前 news-video Python CLI。现有 P0 已支持 TXT/MD/JSON、本地/LLM 可选分镜、PPTX 与 PNG、PCM WAV、MP3、SRT、Timeline、16:9 MP4、技术 QA 和缓存。尚未实现自动新闻采集、新闻事实自动核验、9:16 自动重排、授权裁定、自动发布。

源文件与适配层分离：根目录 skills/ 下存放九个专业 Skill，每个具有 SKILL.md、references/、scripts/、assets/；根目录 agents/ 下存放五个 Agent 的角色契约。各个平台目录仅负责自动发现与调用，不应复制出多套需要独立维护的业务规则。

## 目录与兼容性

| 工具 | 项目 Skills 实际发现位置 | 项目 Agent/Prompt 位置 |
|---|---|---|
| Pi | .agents/skills（本仓库复用）或 .pi/skills | .pi/prompts（原生可调用模板） |
| Codex | .agents/skills | .codex/agents/*.toml |
| Claude Code | .claude/skills | .claude/agents/*.md |
| OpenCode V2 | .agents/skills 或 .claude/skills 或 .opencode/skills | .opencode/agents/*.md |

注意：Pi 的 .pi/agents/ 不等于自动加载的子代理，.codex/skills/ 也不是 Codex 项目 Skill 官方发现目录。因此这两个目录附带明确说明，不误导用户。

本仓库自带 .agents/skills 和 .claude/skills 中的薄入口文件，以对应名称找到根目录的完整 Skill；使用安装器安装到其他项目时，则复制完整的 Skill 目录，而非仅复制入口。

## 安装命令

在克隆仓库后，于仓库根目录运行：

    python scripts/validate_skills.py
    python scripts/install_agents.py --list
    python scripts/install_agents.py --platform all --dry-run
    python scripts/check_environment.py --strict
    python scripts/smoke_test.py --tier static

跨项目安装（将 /path/to/project 替换为真实项目路径）：

    python scripts/install_agents.py --platform all --target /path/to/project
    python scripts/install_agents.py --platform pi --target /path/to/project
    python scripts/install_agents.py --platform codex --target /path/to/project
    python scripts/install_agents.py --platform claude --target /path/to/project
    python scripts/install_agents.py --platform opencode --target /path/to/project

用户级安装：

    python scripts/install_agents.py --platform all --scope user

选项：
- --components skills 或 --components agents：只安装相应资源。
- --dry-run：显示将安装的资源，不写入目标。
- --force：仅在明确同意覆盖已有不同内容文件时使用；从不删除目录中的额外文件。
- 默认拒绝覆盖已改动文件，也拒绝符号链接目录，成功安装之后可以重复运行。
- --scope user 与 --target 不可同时使用。

选择 --platform all 的项目级安装时，Pi/OpenCode 复用 Codex 的 .agents/skills，避免不必要的同名重复；用户级安装为了工具独立，分别采用各工具约定的目录。安装器只复制文件，不执行项目内的诊断脚本或发布操作，且不是整套文件原子事务；遇到后段冲突时，可解决后重新运行。

## 五个角色

| Agent | 职责 | 核心 Skill |
|---|---|---|
| news-producer | 制片编排、阶段交付和结果汇总 | news-pipeline-orchestration、news-quality-gate |
| news-editorial-auditor | 事实、引语、来源与授权核查 | news-input-governance、news-release-review |
| news-storyboard-director | 分镜结构、视觉排版及 PPTX/PNG | news-scene-planning、news-visual-slides |
| news-timing-engineer | 逐句语音、PCM 时间线、字幕与 MP4 同步 | news-voice-production、news-timeline-subtitles、news-video-rendering |
| news-qa-reviewer | 产物完整性与发布阻断 | news-quality-gate、news-release-review |

在 Pi 里可调用 /news-producer 并传入文章路径；在 OpenCode 可 @news-producer；Claude Code 可请求 news-producer 子 Agent；Codex 可要求使用定义在 .codex/agents 的 news-producer 角色。四款工具的角色调用语法和授权机制不完全一致，具体应以宿主当前支持为准。

## Skill 命令示例

下列命令都从本仓库根目录运行。每项均有对应更详细的 references 与 assets：

    news-video plan --input examples/sample_news.md
    news-video run --input examples/sample_news.md --out outputs
    news-video validate outputs/<actual-output-directory>

    python skills/news-input-governance/scripts/audit_input.py examples/sample_news.md
    python skills/news-scene-planning/scripts/audit_scenes.py outputs/<actual-output-directory>/scenes.json
    python skills/news-visual-slides/scripts/audit_slides.py outputs/<actual-output-directory>
    python skills/news-voice-production/scripts/audit_audio.py outputs/<actual-output-directory>
    python skills/news-timeline-subtitles/scripts/audit_timeline.py outputs/<actual-output-directory>
    python skills/news-video-rendering/scripts/audit_video.py outputs/<actual-output-directory>
    python skills/news-quality-gate/scripts/audit_manifest.py outputs/<actual-output-directory>
    python skills/news-release-review/scripts/release_check.py outputs/<actual-output-directory>

其中 release_check.py 总是以退出码 2 表示不可自动发布，即使有人手工把 Manifest 的 public_release_approved 改成 true 也不会解除门禁。P0 尚无身份绑定的人类签核账本；脚本只做人工审批核查提示，不是发布批准执行器。

## Pi 原生发现的实测记录（v0.1.2 本地验证）

本节结论来自真实 Pi 会话，而不是文档推断。

| 项目 | 实测方法 | 结果 |
|---|---|---|
| 项目 Skill 自动发现 | 在仓库根目录启动 Pi 会话，检查注入的 skill 清单 | 9 个 Skill 全部被发现，路径为 `.agents/skills/<name>/SKILL.md` |
| 强制加载 Skill | `pi -p "/skill:news-input-governance 只回复 SKILL_OK"`，再解析 session JSONL | 退出码 0；session 中出现 `<skill name="news-input-governance" location="…/.agents/skills/news-input-governance/SKILL.md">` |
| Skill 内资源可读 | 检查 session 注入内容与仓库路径 | 注入的是**薄入口**，其中指明先去读仓库根的 `skills/<name>/SKILL.md` 与 `references/` / `assets/` / `scripts/`；这些路径在本仓库真实存在（`validate_skills.py` 现在逐个校验） |
| Prompt 模板展开 | `pi -p "/news-producer 只回复 TEMPLATE_OK 这 11 个字符"`，再解析 session JSONL | 退出码 0；session 中存有模板全文，且 `$ARGUMENTS` 已被替换为实际参数 |
| 不把 `.pi/agents/` 当子 Agent | 阅读 `.pi/agents/README.md` 与 Pi 官方说明 | Pi 不会把 `.pi/agents/*.md` 当自动加载的子 Agent；本仓库也未声称已集成子 Agent 执行 |

**重要差异**：Pi 强制加载 Skill 时注入的是 `.agents/skills` 下的薄入口，完整 playbook 需要模型再读一次仓库内的规范文件。这不影响本仓库使用（入口里的路径已由校验器保证存在），但意味着“加载了 Skill”与“读完了 playbook”不是同一事件；如果希望一步到位，可在其他项目直接安装完整 Skill 目录（安装器就是这么做的）。

## 开发与维护

1. 根目录 skills/ 是业务 Skill 真相来源，修改后维护 reference/asset/script 和相关测试。
2. 修改 Agent 时核对 agents/ 与四类原生入口；尤其不能将 Pi prompt 误认作真正独立执行的子 Agent。
3. 所有时间戳必须由真实 PCM 音频采样数计算。SRT/MP4 时间的近似推测禁止。
4. 技术 qa_passed 不包含内容真实、版权许可或公开发布审批。
5. 先跑 python scripts/validate_skills.py 和 PYTHONPATH=src pytest -q，修改媒体环节再补真实 FFmpeg/TTS E2E。
6. 不上传 API Keys、用户素材、生成视频音频或模型权重。
7. SKILL.md 中反引号包住的仓库路径会被 `validate_skills.py` 逐个解析；写了就必须真实存在，否则校验失败（回归测试：`tests/test_agent_assets.py::test_validator_fails_when_a_promised_resource_disappears`）。

详见 docs/agent-integration-review.md、docs/architecture.md、docs/roadmap.md 及根目录 AGENTS.md。
