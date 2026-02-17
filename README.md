# 极简语音识别字幕工坊 ZMv6

高稳定、可维护、可扩展的音视频转 SRT 项目。基于 Flask + FFmpeg + Deepgram/HF。

> 本版本是对 `zmv5` 的兼容升级版，保留原有核心 API 路径与主要环境变量，重点优化稳定性、字幕质量、可运维性。

---

## 这次升级了什么（v6）

### 1) 稳定性升级
- ✅ **任务队列 + Worker 模型**：`/api/start` 不再阻塞，任务入队后后台执行。
- ✅ **心跳与孤儿任务回收**：卡死任务会被标记为 error，避免长期“跑飞”。
- ✅ **元数据脏写机制**：减少高频磁盘写入，提升并发稳定性。
- ✅ **重启恢复能力**：历史任务元数据会自动恢复，`queued/running` 可重入队。

### 2) 识别质量升级
- ✅ **CJK 空格修复**：自动去除中文/日文字符之间错误空格（解决 `一 个 字 空 格` 现象）。
- ✅ **智能分句生成 SRT**：按标点与长度切分，避免一大坨字幕长期挂屏。
- ✅ **时间分配优化**：切分后字幕按文本权重分配时间，更接近自然阅读节奏。

### 3) 接口与安全升级
- ✅ 新增 `POST /api/cancel/<job_id>` 任务取消。
- ✅ 新增 `GET /api/health` 健康探针。
- ✅ 新增 `GET /api/config` 配置读取。
- ✅ 可选 `API_AUTH_TOKEN` 鉴权（默认关闭，兼容旧版）。

### 4) 前端体验升级
- ✅ 增加“取消当前任务”按钮。
- ✅ 增加参数自动保存（`localStorage`）。
- ✅ 状态与日志回传更完整（error / cancel）。

---

## 目录结构

```text
.
├─ app.py
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
├─ .env.example
├─ templates/
│  └─ index.html
├─ static/
│  ├─ app.js
│  └─ style.css
└─ jobs/
   ├─ uploads/
   ├─ tmp/
   ├─ outputs/
   └─ meta/
```

---

## 快速启动

### 1) 准备配置

```bash
cp .env.example .env
# 编辑 .env，至少填 DEEPGRAM_API_KEY
```

### 2) Docker 启动

```bash
docker compose up -d --build
```

> 构建阶段已切换为 `uv pip` 安装依赖（更快），并将 `torchaudio` 约束为 `<2.9` 以避免 `torchcodec` 依赖报错。

默认端口 `8020`（容器内 `7860`）。

---

## 主要接口（保持兼容）

- `POST /api/start` 上传并启动任务
- `GET /api/status/<job_id>?since=<seq>` 查询状态和增量日志
- `GET /api/download/<job_id>` 下载字幕
- `GET /api/balance?project_id=...` 查询余额

### 新增
- `POST /api/cancel/<job_id>` 取消任务
- `GET /api/health` 健康状态
- `GET /api/config` 服务配置

---

## 关键环境变量说明（含兼容项）

| 变量 | 作用 | 默认 |
|---|---|---|
| `DEEPGRAM_API_KEY` | Deepgram Key | 空 |
| `DEEPGRAM_BASE_URL` | Deepgram API Base | `https://api.deepgram.com/v1` |
| `DEFAULT_MODEL` | 默认模型 | `nova-2-general` |
| `CONCURRENCY` | 片段并发数 | `20` |
| `JOB_WORKERS` | 同时执行任务数 | `1` |
| `MAX_UPLOAD_MB` | 上传大小限制(MB) | `4096` |
| `AUTO_CLEANUP_ENABLED` | 自动清理开关 | `1` |
| `DONE_RETENTION_SECONDS` | 成功任务保留秒数 | `7200` |
| `ERROR_RETENTION_SECONDS` | 失败任务保留秒数 | `86400` |
| `ORPHAN_RETENTION_SECONDS` | 孤儿任务判定秒数 | `86400` |
| `AUTO_CLEANUP_AFTER_DOWNLOAD` | 下载后清理 | `0` |
| `DOWNLOAD_GRACE_SECONDS` | 下载后宽限秒数 | `60` |
| `SECURE_DELETE_PASSES` | 删除覆盖轮次 | `0` |
| `API_AUTH_TOKEN` | 接口鉴权令牌（可选） | 空 |
| `VAD_CPU_THREADS` | Silero VAD CPU 线程数 | `CPU核数` |
| `ENABLE_ONNX_VAD` | 启用 ONNX Runtime 加速 | `1` |

---

## 迁移说明（从 v5 到 v6）

1. 用本项目替换原目录中的 `app.py / static / templates / Docker* / requirements.txt`。
2. 保留原 `.env`，新增变量可按需补充（不填也能跑）。
3. 重建镜像：`docker compose up -d --build`。
4. 首次启动建议观察日志：`docker logs -f stt_subtitle_webapp`。

---

## 常见问题

### Q1: 为什么字幕仍可能偏长？
- 可能源音频本身停顿少，VAD 很难切；可调大 `utterance_split`（例如 0.8 或 1.0）。

### Q2: 中文仍有不自然空格怎么办？
- v6 已做 CJK 空格清洗。若仍出现，可切换 `nova-2-general` 并开启 `punctuate + smart_format`。

### Q3: 如何提升吞吐？
- 提高 `CONCURRENCY`（片段并发）和 `JOB_WORKERS`（任务并发），同时提升机器 CPU/带宽。

### Q4: Silero VAD 太慢怎么调？
- 现在默认会使用 `VAD_CPU_THREADS=CPU核数`，并优先尝试 ONNX Runtime（官方推荐的 CPU 加速路径）。
- 可在 `.env` 里显式设置 `VAD_CPU_THREADS`（例如 16/32）并保持 `ENABLE_ONNX_VAD=1`。
- 如果你的机器 CPU 核数多但系统负载高，可把 `CONCURRENCY` 调低一点，给 VAD 阶段留出更多 CPU。

---

## 许可证

MIT
