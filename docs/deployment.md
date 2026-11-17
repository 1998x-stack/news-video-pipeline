# 部署、配置与运行策略

## 三种推荐配置

### A. 本地离线 smoke test

`planner.provider: heuristic`，`voice.provider: espeak`。不依赖 API Token，可创建可验证的全部五件套；中文 TTS 音色机械，不建议直接发布。

### B. 面向内容创作的 API 方案

`planner.provider: openai-compatible` + 已获授权的 TTS Provider（当前 Edge 适合试验，正式生产可自行扩展商业服务）+ `quality.whisper_check: true`。通过 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` 传入机密和模型。建议内容审核后才合成或发布，以减少无效成本。

### C. 本地模型方案（预留扩展）

新建 `TTSProvider` 适配器接入 CosyVoice 或 Qwen3-TTS，将生成数据标准化为 mono PCM WAV；现阶段未包含这两个推理服务的部署脚本，**不能认为配置名已经支持直接使用**。Whisper 的 `faster-whisper` 已接入可选 ASR 质检，需要下载模型。

## 运行边界

- 完整输出和 TTS 缓存保存在 `outputs/`，默认 `.gitignore` 忽略。生产建议挂载持久化卷，并按日期/源素材写外部索引。
- 多 worker 运行时，同一 run id 通过 POSIX flock 串行；不同 run id 可共享 TTS 缓存，缓存写入使用原子 rename。
- 当前无自动清理策略。生产建议定期归档历史 MP4、缓存文件，并加磁盘阈值告警。
- 敏感配置禁止进入 Git。API 超时/无权限/错误格式均会让任务失败，不会默默退回规则规划。
- 源文本超过分镜上限会明确失败，禁止静默截断。长文章需调整 `max_scenes` 或在 P1 引入章节切分。
- Docker 不提供 HTTP 服务与计划任务。定时调用请使用宿主 cron/systemd timer/Kubernetes CronJob，输出独立挂载路径。

## Linux 每晚 20:00 的计划任务示例

**注意：系统时区需显式设置为 Asia/Shanghai；这里的输入文件应由单独的、已完成验证的数据采集流程提供。**

```cron
CRON_TZ=Asia/Shanghai
0 20 * * * cd /srv/news-video-pipeline && /srv/news-video-pipeline/.venv/bin/news-video run --input /data/daily-$(TZ=Asia/Shanghai date +\%F).md --out /data/video-outputs >> /var/log/news-video.log 2>&1
```

实际生产应引入轮询/等待输入就绪与锁，避免 20:00 时源文字稿还没发布。P0 不提供自动新闻抓取与发布。
