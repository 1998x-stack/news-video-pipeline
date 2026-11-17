---
name: news-scene-planning
description: Turn a verified Chinese news manuscript into deterministic or LLM-assisted Scene records without silent truncation; use when creating or auditing news storyboards.
---

# 场景规划｜news-scene-planning

## 何时使用
当用户需要场景规划能力、优化对应工程模块或核对产物时使用；先阅读 `references/scene-contract.md`，需要执行前先检查 `assets/scene-example.json`。

## 对应实际代码
`src/news_video_pipeline/planner.py,models.py`。本 Skill 是对现有功能的可调用说明，不能把路线图项目描述为已实现。

## 输入与可交付物
- 输入：标题、正文、planner.max_scenes、max_chars_per_scene、可选 LLM 端点
- 输出：scenes.json: id/title/body/sentences/source_id

## 标准执行流程
1. 默认执行 heuristic 规则规划；预览 scenes 数量、每句文本与源文字的可追溯性。
2. 每个 Scene 的句子必须可直接逐句合成 TTS；避免把一条新闻拆到语义断裂。
3. 超过 max_scenes 时明确失败并提示修改配置，不得截断。
4. LLM 模式仅生成待人工编辑草稿；检查是否新增数字、机构、政策、年份或不受原稿支持的推理。

## 校验命令
在仓库根目录运行：
```bash
news-video plan --input examples/sample_news.md
```

同时运行 `PYTHONPATH=src pytest -q`；修改媒体逻辑时需使用真实依赖执行 `news-video run` 并检查 `qa_report.json`。

## 不可破坏的不变量
- Scene id 唯一且顺序稳定，sentences 非空；字段升级需同步 schema_version 与测试。
- 未验证 LLM 分镜不得视为事实核验完成。
- 不允许伪造新闻事实、授权或发布状态。无法验证时返回需要人工复核。

## 当前实现边界
规则切分并非语义总结，LLM 规划需要人工核查；P1 证据映射 Schema 尚未实现。

## 资源
- `references/scene-contract.md`：细化契约、错误场景、检查点与回退策略
- `scripts/audit_scenes.py`：独立诊断工具（只读或明确调用 CLI）
- `assets/scene-example.json`：机器可读的审核模板
- 项目约束：根目录 `AGENTS.md`、`docs/architecture.md`、`docs/roadmap.md`
