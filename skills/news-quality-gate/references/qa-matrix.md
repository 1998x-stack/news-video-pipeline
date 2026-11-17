# 质量与归档验收：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/quality.py,pipeline.py`
- 输入契约：output directory、scenes/timeline、manifest、PPTX/PNG/WAV/SRT/MP4
- 成功产物：qa_report.json、manifest.json 以及可复验判定
- 已实现边界：当前 QA 未建立可审计事实证据链、音频响度标准或人工签核系统

## 2. 分阶段操作

### 1. 检查点 1
先验证所有产物非空、Scene/PPTX/PNG 数一致、字幕条数与 Cue 数一致。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
比对 WAV 样本时长与 Timeline，并使用 ffprobe 检验轨道、画面尺寸和视频时长误差。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
验证 manifest.sha256 全部文件哈希，避免使用损坏缓存。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
将 qa_passed 限定为技术完整性；public_release_approved=false 和 rights_status=unverified 不得自动改写。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] 输出目录需包含完整 manifest，所有 manifest 路径必须局限于输出目录。
- [ ] 处理失败应显式非零退出，禁止通过生成空成功标志避开检查。
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
python skills/news-quality-gate/scripts/audit_manifest.py outputs/<run-id>
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
