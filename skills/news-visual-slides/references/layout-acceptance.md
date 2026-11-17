# PPTX / PNG：工程参考与验收规范

## 1. 定位和真相来源

- 对应模块：`src/news_video_pipeline/slides.py`
- 输入契约：Scene[]、标题、render.width/height/font_path、中文字体
- 成功产物：presentation/daily.pptx；presentation/slides/slide_NNN.png
- 已实现边界：当前固定 16:9 静态幻灯片，无 9:16 自动布局、动画或语义可视化引擎

## 2. 分阶段操作

### 1. 检查点 1
同一 Scene 驱动 PPTX 原生可编辑文本和 PIL PNG 画面，不能将 PPTX 简化为截图。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 2. 检查点 2
优先检查字形支持、2 行标题/7 行正文限制、页脚遮挡和页码。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 3. 检查点 3
根据 scenes 数量逐一校验 PPTX slide 数与 PNG 数；视频以 PNG 为像素画面源。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

### 4. 检查点 4
排版修改前后运行端到端回归并记录渲染环境、字体与尺寸。
失败时必须保留可定位的文件/异常与运行条件，而不是跳过当前阶段。

## 3. 验收门禁

- [ ] PPTX 与 PNG 内容应逻辑一致，但不同排版引擎不保证像素级相同。
- [ ] 超出版面时报错而不是裁剪文字。
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
python skills/news-visual-slides/scripts/audit_slides.py outputs/<run-id>
```

详见 `docs/architecture.md` 与 `AGENTS.md`；任何 P1/P2 建议先形成提案，不自动声称功能已交付。
