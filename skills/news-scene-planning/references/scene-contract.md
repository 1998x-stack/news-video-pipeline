# 场景规划：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/planner.py,models.py`
- 输入契约：标题、正文、planner.max_scenes、max_chars_per_scene、可选 LLM 端点
- 成功产物：scenes.json: id/title/body/sentences/source_id
- 已实现边界：规则切分并非语义总结，LLM 规划需要人工核查；P1 证据映射 Schema 尚未实现

## 2. 分阶段操作

### 1. 检查点 1
默认执行 heuristic 规则规划；预览 scenes 数量、每句文本与源文字的可追溯性。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
每个 Scene 的句子必须可直接逐句合成 TTS；避免把一条新闻拆到语义断裂。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
超过 max_scenes 时明确失败并提示修改配置，不得截断。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
LLM 模式仅生成待人工编辑草稿；检查是否新增数字、机构、政策、年份或不受原稿支持的推理。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] Scene id 唯一且顺序稳定，sentences 非空；字段升级需同步 schema_version 与测试。
- [ ] 未验证 LLM 分镜不得视为事实核验完成。
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
news-video plan --input examples/sample_news.md
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
