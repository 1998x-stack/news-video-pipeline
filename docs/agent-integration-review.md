# 多平台 Agent/Skill 工程深度评审

## 一、已实现系统事实

代码主链路为 planner.read_input -> planner.plan -> slides.render_slides + timeline.make_audio_and_timeline -> timeline.write_srt -> video.render_video -> quality.validate_outputs -> pipeline manifest。

- 输入支持 TXT / MD / JSON，单文稿 3 MB，不能静默丢失内容。
- Scene 数据模型包含 id/title/body/sentences/source_id；Scenes 为视觉页与配音句子的共同输入。
- PPTX 为可编辑 PowerPoint 原生元素；PNG 经 PIL 生成，并非保证与 PPTX 像素一致。
- 每句 TTS 先规范化为 mono 16-bit PCM WAV，用 getnframes 形成时钟，再生成 timeline 和 SRT。
- FFmpeg 以图像与音频合成静态 16:9 MP4；MP3 不作为字幕主时钟。
- QA 检查页数、时间线、字幕条数、实际 WAV 时长、视频轨道与偏差。
- pipeline 基于文件与配置哈希定位运行、POSIX flock 防重复，并在成功验收后原子提交目录。

## 二、Agent 应该操作哪些边界

Skills 描述步骤、契约和诊断方法；Agents 负责选择调用与结果解释；宿主权限负责实际文件、网络、命令执行授权。

强约束：
- 不因 Agent 写出的新闻事实而认为已证实。
- 不以测试正弦音 synthetic 代替公开发布的旁白。
- 不让不同 Agent 分别估算字幕和视频时长；唯一音频时钟来自 PCM sample count。
- 不根据技术 QA 状态自造平台发布 ID、许可证状态或人工签名。
- 一切失效、未验证素材和外部 API 问题应显式失败或列入人工待办。

## 三、为什么要兼容多种原生配置

Codex 项目级 Skills 位于 .agents/skills，原生自定义 agent 可定义为 .codex/agents 的 TOML；Claude Code 原生使用 .claude/skills 和 .claude/agents；OpenCode V2 使用 .opencode/agents，Skills 可兼容 .agents/skills；Pi 原生 prompt templates 位于 .pi/prompts，且支持 .agents/skills 的 Skill 自动发现。

因此不能简单复制一份 AGENTS.md 到四个目录后声称多 Agent 已集成。真正可发现的适配文件需要遵循各自的文件格式；Pi prompt 本身不等于多实例子代理，子代理执行需要额外扩展。

## 四、未交付能力

这次完成的是技能知识库、原生 Agent 角色入口、只读诊断脚本、安装器和回归测试，不应算作 P1/P2 内容功能实现。仍然待完成：
- SourceEvidence/StoryClaim 证据链、版权自动核查与人工签核后台；
- 9:16 重排、动态转场、硬字幕、词级对齐；
- 商业授权中文 TTS 适配及稳定批处理资源管理；
- 多平台 OAuth 上传、发布幂等、反馈指标；
- 多阶段 DAG 缓存与完整可回滚部署。

## 五、验收表

| 目标 | 验证方式 |
|---|---|
| 技能元数据可识别 | python scripts/validate_skills.py |
| Skill 承诺的资源真实存在 | validate_skills.py 解析 SKILL.md/适配器中的仓库路径；`tests/test_agent_assets.py` |
| 可移植安装路径 | pytest -q tests/test_agent_assets.py |
| 安装冲突与重复运行 | 上述 installer tests |
| P0 Python 核心不回归 | PYTHONPATH=src pytest -q |
| 真实 FFmpeg/TTS 视频可生成 | python scripts/smoke_test.py --tier all-offline |
| 真实 LLM 规划可用且不虚构事实 | python scripts/smoke_test.py --tier llm --input <稿件> |
| 技术验收 | news-video validate（重算 manifest 哈希）及 audit_manifest.py |
| 防止自动发布 | release_check.py 在未批准包上返回 2 |
| Pi 真实发现 Skill / Prompt | `/skill:news-input-governance`、`/news-producer <参数>` 后检查 session JSONL（见 docs/agent-skills.md） |

## 六、残余风险

- 安装器是文件级原子写入，而不是整套资源事务；发现覆盖冲突时可能存在已复制的前序文件。
- Agent 提示不构成沙箱，用户必须审查宿主可执行工具权限，尤其是任意 shell、文件改写与外部上传。
- 代码中的 fcntl 依赖 POSIX，不能宣称 Windows 原生支持。
- 用户级同时为多个工具安装可能发生同名 Skills，被某个工具优先选择；按目标工具单独安装可减少重复。
- 目前诊断脚本只是 Stage sanity checks，不能替代核心 news-video validate、音画人工检查和内容审批。
- 本仓库 `.agents/skills/` 里是薄入口，Pi 加载该 Skill 得到的是“指针 + 约束”，完整 playbook 需要模型再读一次；尚无自动化手段保证模型一定执行第二次读取。
- LLM grounding 守卫是启发式的：拦得住虚构数字/日期与大幅离题，拦不住同义改写造成的语义漂移，也不检查中文汉字数字。

官方机制参考：
- Pi https://docs.pi.dev/latest/skills
- Pi prompts https://docs.pi.dev/latest/prompt-templates
- Codex https://learn.chatgpt.com/docs/customization/overview
- Codex agents https://learn.chatgpt.com/docs/agent-configuration/subagents
- Claude Code https://support.claude.com/en/articles/14554000-claude-code-power-user-tips
- OpenCode https://opencode.ai/docs/agents
- OpenCode skills https://opencode.ai/docs/skills
