# 部署、配置与运行策略

## 三种推荐配置

### A. 本地离线 smoke test

`planner.provider: heuristic`，`voice.provider: espeak`。不依赖 API Token，可创建可验证的全部五件套；中文 TTS 音色机械，不建议直接发布。

### B. 面向内容创作的 API 方案

`planner.provider: openai-compatible` + 已获授权的 TTS Provider（当前 Edge 适合试验，正式生产可自行扩展商业服务）+ `quality.whisper_check: true`。通过 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` 传入机密和模型。建议内容审核后才合成或发布，以减少无效成本。

可直接复制 `config/llm.yaml`（LLM + espeak）或 `config/llm-whisper.yaml`（额外开启 Whisper 复检）。

#### 思维模型网关的实测行为（必读）

本轮在本地网关（`iagent` provider，模型 ID `iagent/standard`，网关返回的真实模型名为 `DeepSeek-V4-Flash`）上实测到三个容易踩的坑，已在代码中提供对应开关：

| 现象 | 实测证据 | 配置应对 |
|---|---|---|
| 思维链吃掉全部输出预算，接口 200 但 `content` 为空，`finish_reason=length` | `max_tokens=8192` 的流式请求把 70 000+ 字节的 SSE 全部花在 `reasoning` 上 | 提高 `planner.max_tokens`（默认 8192） |
| 思维链极长，单次调用 75–495 秒 | 1.6 千字真实稿件开启思维链时 495 秒才拿到正文，而旧代码硬编码 `timeout=90` → `APITimeoutError` | 流式请求 + `planner.timeout_s`（默认 240） |
| 流式请求会让“总时长”失去兜底 | 一次调用在开启流式后持续挂起超过 900 秒 | `planner.max_total_s`（默认 900）在代码层强制墙钟上限 |

实测有效的关闭思维链方式（本项目已在 `config/llm.yaml` 预设）：

```yaml
planner:
  reasoning_effort: none   # 1.6 千字稿件从“超时”降到约 40 秒，思维链字符数为 0
```

`reasoning_effort` 是可选字段：留空则不发送，避免不支持该参数的端点直接 400。不同厂商的参数名可能不同，**必须以真实接口实测为准**，不要照搬这里的结论。

模型 ID 属于供应商可能随时更新的别名，本项目不声称固定服务版本；请把实际请求的 Model ID 记入 Manifest（`manifest.config.planner.model`）。

#### grounding 守卫

LLM 返回的旁白必须满足两条硬性条件，否则整个任务失败：

1. 旁白中出现的数字/日期（`\d+(?:[.,]\d+)*`）必须能在原文中找到，否则报 `LLM narration contains numbers/dates absent from the source`；
2. 旁白与原文的字符匹配率（忽略标点与空白，`difflib` 匹配块）不得低于 `planner.min_source_coverage`（默认 0.75）。

本机三期新闻联播真实稿件的实测匹配率为 **1.000**，未检测到虚构数字，说明阈值有充足余量。该守卫是启发式的：它拦不住同义改写造成的语义偏移，也拦不住中文数字（如“二十届”）被改成别的汉字数字。**技术守卫不能替代人工事实核验。**

### C. 本地模型方案（预留扩展）

新建 `TTSProvider` 适配器接入 CosyVoice 或 Qwen3-TTS，将生成数据标准化为 mono PCM WAV；现阶段未包含这两个推理服务的部署脚本，**不能认为配置名已经支持直接使用**。Whisper 的 `faster-whisper` 已接入可选 ASR 质检，需要下载模型。

## 运行边界

- 完整输出和 TTS 缓存保存在 `outputs/`，默认 `.gitignore` 忽略。生产建议挂载持久化卷，并按日期/源素材写外部索引。
- 多 worker 运行时，同一 run id 通过 POSIX flock 串行；不同 run id 可共享 TTS 缓存，缓存写入使用原子 rename。
- 当前无自动清理策略。失败或被中止的运行会保留 `.building-*` 暂存目录（整期长稿约 170–180 MB），生产建议定期归档历史 MP4、缓存文件，并加磁盘阈值告警。
- 敏感配置禁止进入 Git。API 超时/无权限/错误格式均会让任务失败，不会默默退回规则规划。
- 源文本超过分镜上限会明确失败，禁止静默截断。整期长稿（约 6–7 千字 → 60–80 个场景）请使用 `config/longform.yaml` 提高 `planner.max_scenes`。
- Docker 不提供 HTTP 服务与计划任务。定时调用请使用宿主 cron/systemd timer/Kubernetes CronJob，输出独立挂载路径。

## 部署自检清单

```bash
python scripts/check_environment.py --strict --out outputs/local/environment.json
python scripts/validate_skills.py
python scripts/smoke_test.py --tier all-offline --report outputs/local/smoke.json
news-video validate outputs/<实际输出目录>
python skills/news-quality-gate/scripts/audit_manifest.py outputs/<实际输出目录>
python skills/news-release-review/scripts/release_check.py outputs/<实际输出目录>   # 恒以退出码 2 表示未获人工批准
```

`check_environment.py` 只把凭据报告为 `set`/`unset`，不输出长度或前缀；报告可直接贴给下一个审阅者。

## Linux 每晚 20:00 的计划任务示例

**注意：系统时区需显式设置为 Asia/Shanghai；这里的输入文件应由单独的、已完成验证的数据采集流程提供。**

```cron
CRON_TZ=Asia/Shanghai
0 20 * * * cd /srv/news-video-pipeline && /srv/news-video-pipeline/.venv/bin/news-video run --input /data/daily-$(TZ=Asia/Shanghai date +\%F).md --out /data/video-outputs >> /var/log/news-video.log 2>&1
```

实际生产应引入轮询/等待输入就绪与锁，避免 20:00 时源文字稿还没发布。P0 不提供自动新闻抓取与发布。
