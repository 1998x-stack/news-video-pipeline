# 统一编排：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/cli.py,pipeline.py,config.py`
- 输入契约：输入文件、配置文件、目标目录、可选 --force
- 成功产物：可重放 output run_id、manifest、qa_report；失败诊断目录
- 已实现边界：不是 DAG 粒度恢复/调度器；定时采集及外部发布还在后续路线图

## 2. 分阶段操作

### 1. 检查点 1
先通过 plan 预览场景和输入限制；确保依赖 ffmpeg/ffprobe、Noto 中文字体、TTS 已可用。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
以内容+配置+版本哈希建立 run_id；同一 run id 上锁，成功且哈希有效则复用。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
运行 render PPTX/PNG → per-sentence TTS → timeline/SRT → FFmpeg → QA，然后原子提交目标目录。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
失败时保留 .building-* 诊断目录并中止；不能把未完成目录当作成功产物。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] 默认无自动采集或发布行为；--force 应明确由操作者指定。
- [ ] 当前使用 POSIX fcntl，不保证原生 Windows 下直接运行。
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
python skills/news-pipeline-orchestration/scripts/run_pipeline.py --input examples/sample_news.md --out outputs --plan-only
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
