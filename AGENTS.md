# Agent / Contributor 约束

1. **新闻事实不可凭空生成**。用户输入是唯一事实来源，LLM 不能添加未提供的数据、引用、机构或日期；默认生成结果要求人工复核。
2. **时钟只有一个**：TTS 音频转为 mono PCM WAV 后，以采样数计算时间。不要采用估算语速后补 SRT 的策略，也不要把 MP3 时长当成精确主时钟。
3. `Scene` → PPTX/PNG；`Sentence WAV` → timeline/SRT/MP3/MP4。修改数据模型必须同时升级 `schema_version` 和测试。
4. **失败关闭**：不存在/非法文件、场景溢出、音频失效、视频解码失败、字幕错位必须抛错，不能以 `qa_passed` 静默跳过。
5. 原始输入不得偷偷截断。有限制时主动报错；无法核实的新闻和无权使用的截图不得自动发布。
6. 保持 Provider 可替换：OpenAI-compatible LLM、TTS、Whisper ASR 都是可选依赖。无需任何在线 API 的测试必须始终能运行。
7. 不提交 `.env`、用户素材、真实 API Keys、生成的 MP3/MP4、缓存或大模型权重。不要设置任何默认自动发布动作。
8. 每次 PR 至少运行 `PYTHONPATH=src pytest -q`，涉及真实 TTS/视频时运行 sample 端到端并检查 `qa_report.json`。更新 README/roadmap 标记实际功能，不夸大尚未实现的模块。
9. 生产系统需固定 ffmpeg、字体、TTS 模型及代码依赖版本，记录可复现环境信息。当前哈希仅对本软件版本/用户配置有效，不能保证跨机器字节一致。
10. B站、抖音和 YouTube 上传权限与内容版权分离；必须单独审核授权和发布行为。


## 新增：Agents 与 Skills 维护约束

11. 根目录 `skills/` 是九个可迁移技能的真相来源；`agents/` 为五个跨平台角色契约；不得在四种平台适配层私自修改业务规则。
12. Pi 采用 `.pi/prompts`，不将 `.pi/agents` 误认为原生子代理；Codex 采用 `.agents/skills`；Claude 采用 `.claude/skills`；OpenCode V2 采用 `.opencode/agents`。
13. 任何改动至少运行 `python scripts/validate_skills.py` 与 `PYTHONPATH=src pytest -q`；技术验收与人工新闻事实/权利/发布验收严格区分。
