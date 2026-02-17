# -*- coding: utf-8 -*-
"""
ZMv6 - Ultra-Stable STT Studio
-------------------------------------------------
在 v5 基础上进行全面升级：
1) 稳定性：任务队列 + 工作线程 + 心跳 + 孤儿任务回收
2) 安全性：可选 API Token 鉴权、下载令牌支持、敏感信息不落日志
3) 质量：文本清洗（修复 CJK 字符间空格）、智能分句、更可读 SRT
4) 性能：元数据脏写 + 批量落盘，减少高频 I/O
5) 兼容性：尽量保持原有配置名和 API 路径
"""

from __future__ import annotations

import copy
import html
import json
import os
import queue
import random
import re
import shutil
import string
import subprocess
import threading
import time
import traceback
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import torch
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from requests.adapters import HTTPAdapter
from silero_vad import get_speech_timestamps, load_silero_vad, read_audio
from urllib3.util.retry import Retry
from werkzeug.utils import secure_filename

load_dotenv(override=True)


# -----------------------------
# 环境变量读取工具
# -----------------------------
def _env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return (v if v is not None else default).strip()


def _env_int(name: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    raw = os.getenv(name)
    try:
        val = int(raw) if raw is not None else int(default)
    except Exception:
        val = int(default)
    if minimum is not None:
        val = max(minimum, val)
    if maximum is not None:
        val = min(maximum, val)
    return val


def _env_float(name: str, default: float, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    raw = os.getenv(name)
    try:
        val = float(raw) if raw is not None else float(default)
    except Exception:
        val = float(default)
    if minimum is not None:
        val = max(minimum, val)
    if maximum is not None:
        val = min(maximum, val)
    return val


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


# -----------------------------
# 配置
# -----------------------------
class Config:
    APP_TITLE = _env_str("APP_TITLE", "极简语音识别字幕工坊")

    # 鉴权（可选，为兼容默认关闭）
    API_AUTH_TOKEN = _env_str("API_AUTH_TOKEN", "")

    # Deepgram / HF
    DEEPGRAM_API_KEY = _env_str("DEEPGRAM_API_KEY", "")
    DEEPGRAM_BASE_URL = _env_str("DEEPGRAM_BASE_URL", "https://api.deepgram.com/v1").rstrip("/")
    HF_TOKEN = _env_str("HF_TOKEN", "")
    HF_KOTOBA_URL = _env_str(
        "HF_KOTOBA_URL",
        "https://api-inference.huggingface.co/models/kotoba-tech/kotoba-whisper-v2.2",
    )
    ENABLE_LOCAL_KOTOBA = _env_bool("ENABLE_LOCAL_KOTOBA", False)

    # 上传与运行限制
    MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 4096, minimum=1)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    CONCURRENCY = _env_int("CONCURRENCY", 20, minimum=1, maximum=64)  # 片段并发
    JOB_WORKERS = _env_int("JOB_WORKERS", 1, minimum=1, maximum=8)  # 同时跑几个任务

    # 请求与重试
    REQUEST_TIMEOUT_SECONDS = _env_int("REQUEST_TIMEOUT_SECONDS", 120, minimum=10, maximum=600)
    REQUEST_RETRY_TIMES = _env_int("REQUEST_RETRY_TIMES", 2, minimum=0, maximum=6)

    # 清理策略
    AUTO_CLEANUP_ENABLED = _env_bool("AUTO_CLEANUP_ENABLED", True)
    CLEANUP_INTERVAL_SECONDS = _env_int("CLEANUP_INTERVAL_SECONDS", 120, minimum=10)
    DONE_RETENTION_SECONDS = _env_int("DONE_RETENTION_SECONDS", 7200, minimum=60)
    ERROR_RETENTION_SECONDS = _env_int("ERROR_RETENTION_SECONDS", 86400, minimum=60)
    ORPHAN_RETENTION_SECONDS = _env_int("ORPHAN_RETENTION_SECONDS", 86400, minimum=60)

    # 下载后自动清理（向后兼容默认关闭）
    AUTO_CLEANUP_AFTER_DOWNLOAD = _env_bool("AUTO_CLEANUP_AFTER_DOWNLOAD", False)
    DOWNLOAD_GRACE_SECONDS = _env_int("DOWNLOAD_GRACE_SECONDS", 60, minimum=0)
    SECURE_DELETE_PASSES = _env_int("SECURE_DELETE_PASSES", 0, minimum=0, maximum=3)

    # 模型与语言
    DEFAULT_MODEL = _env_str("DEFAULT_MODEL", "nova-2-general")
    SUPPORTED_LANG = {"auto", "zh", "en", "ja"}
    SUPPORTED_MODELS = {
        "nova-2-general",
        "nova-3-general",
        "whisper-large",
        "kotoba-tech/kotoba-whisper-v2.2",
    }

    # 质量调优
    MAX_SEGMENT_SECONDS = _env_float("MAX_SEGMENT_SECONDS", 15.0, minimum=5.0, maximum=30.0)
    MIN_SEGMENT_SECONDS = _env_float("MIN_SEGMENT_SECONDS", 0.25, minimum=0.1, maximum=2.0)
    MIN_TRANSCRIBE_SEGMENT_SECONDS = _env_float("MIN_TRANSCRIBE_SEGMENT_SECONDS", 0.45, minimum=0.2, maximum=2.0)
    SHORT_SEGMENT_MERGE_GAP_SECONDS = _env_float("SHORT_SEGMENT_MERGE_GAP_SECONDS", 0.2, minimum=0.0, maximum=1.0)

    # Silero VAD（神经网络）
    SILERO_VAD_THRESHOLD = _env_float("SILERO_VAD_THRESHOLD", 0.50, minimum=0.1, maximum=0.95)
    SILERO_MIN_SILENCE_MS = _env_int("SILERO_MIN_SILENCE_MS", 400, minimum=50, maximum=3000)
    SILERO_MIN_SPEECH_MS = _env_int("SILERO_MIN_SPEECH_MS", 220, minimum=50, maximum=3000)
    SILERO_SPEECH_PAD_MS = _env_int("SILERO_SPEECH_PAD_MS", 120, minimum=0, maximum=1000)
    VAD_PRESET_DEFAULT = _env_str("VAD_PRESET_DEFAULT", "general").lower()
    VAD_CPU_THREADS = _env_int("VAD_CPU_THREADS", os.cpu_count() or 1, minimum=1, maximum=256)
    VAD_INTEROP_THREADS = _env_int("VAD_INTEROP_THREADS", 1, minimum=1, maximum=64)
    ENABLE_ONNX_VAD = _env_bool("ENABLE_ONNX_VAD", True)

    # 元数据写盘节流
    META_FLUSH_INTERVAL_SECONDS = _env_float("META_FLUSH_INTERVAL_SECONDS", 0.8, minimum=0.2, maximum=5.0)
    LOG_MAX_LINES = _env_int("LOG_MAX_LINES", 1000, minimum=100, maximum=10000)
    META_LOG_MAX_LINES = _env_int("META_LOG_MAX_LINES", 500, minimum=50, maximum=5000)

    # 上传名白名单（扩展名兜底）
    ALLOWED_EXT = {
        ".mp3", ".wav", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".opus", ".webm",
        ".mov", ".mkv", ".mpeg", ".mpg", ".mpga", ".mpe", ".3gp", ".m4v", ".avi",
    }

    @classmethod
    def print_info(cls) -> None:
        print(f"--- [v6.0] {cls.APP_TITLE} 启动中 ---")
        print(
            f"任务工作线程: {cls.JOB_WORKERS} | 片段并发: {cls.CONCURRENCY} | 上传限制: {cls.MAX_UPLOAD_MB}MB"
        )
        print(
            "清理机制: "
            f"{'开启' if cls.AUTO_CLEANUP_ENABLED else '关闭'} | "
            f"成功保留 {cls.DONE_RETENTION_SECONDS}s | 失败保留 {cls.ERROR_RETENTION_SECONDS}s | 孤儿阈值 {cls.ORPHAN_RETENTION_SECONDS}s"
        )
        print(f"API 鉴权: {'开启' if cls.API_AUTH_TOKEN else '关闭(兼容模式)'}")
        print(
            f"VAD 加速: threads={cls.VAD_CPU_THREADS} interop={cls.VAD_INTEROP_THREADS} onnx={'on' if cls.ENABLE_ONNX_VAD else 'off'}"
        )


ROOT_DIR = Path(__file__).resolve().parent
JOBS_ROOT = ROOT_DIR / "jobs"
UPLOADS_ROOT = JOBS_ROOT / "uploads"
TMP_ROOT = JOBS_ROOT / "tmp"
OUTPUTS_ROOT = JOBS_ROOT / "outputs"
META_ROOT = JOBS_ROOT / "meta"
LOCK_ROOT = JOBS_ROOT / "locks"

for p in (UPLOADS_ROOT, TMP_ROOT, OUTPUTS_ROOT, META_ROOT, LOCK_ROOT):
    p.mkdir(parents=True, exist_ok=True)


app = Flask(__name__)
app.config["SECRET_KEY"] = _env_str("FLASK_SECRET_KEY", "change-me")
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH


# -----------------------------
# 运行时状态
# -----------------------------
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
META_DIRTY: set[str] = set()
META_DIRTY_LOCK = threading.RLock()

JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
SHUTDOWN = threading.Event()

EMPTY_SEGMENT_ERRORS = {"EMPTY_TRANSCRIPT", "EMPTY_AFTER_NORMALIZE", "HF_EMPTY_TRANSCRIPT"}

SESSION = requests.Session()
retries = Retry(
    total=Config.REQUEST_RETRY_TIMES,
    connect=Config.REQUEST_RETRY_TIMES,
    read=Config.REQUEST_RETRY_TIMES,
    backoff_factor=0.6,
    status_forcelist=(408, 429, 500, 502, 503, 504),
    # 转写 POST 非幂等，避免自动重试导致重复计费或重复提交。
    allowed_methods=frozenset(["GET"]),
)
adapter = HTTPAdapter(max_retries=retries, pool_connections=32, pool_maxsize=128)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

torch.set_num_threads(Config.VAD_CPU_THREADS)
try:
    torch.set_num_interop_threads(Config.VAD_INTEROP_THREADS)
except RuntimeError:
    # 某些运行时在线程池初始化后不可重复设置 interop 线程，忽略即可。
    pass

if Config.ENABLE_ONNX_VAD:
    try:
        SILERO_MODEL = load_silero_vad(onnx=True)
        app.logger.info("Silero VAD runtime: ONNX")
    except Exception as e:
        app.logger.warning(f"Silero ONNX 初始化失败，回退 PyTorch runtime: {e}")
        SILERO_MODEL = load_silero_vad()
else:
    SILERO_MODEL = load_silero_vad()


# -----------------------------
# 工具函数
# -----------------------------
def ts() -> float:
    return time.time()


def dg_url(path: str) -> str:
    # 兼容用户可能传了 .../v1 或不带 /v1
    base = Config.DEEPGRAM_BASE_URL
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/v1/{path.lstrip('/')}"


def mask_secret(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep * 2) + s[-keep:]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    with open(tmp, "a", encoding=encoding) as f:
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def secure_delete_file(path: Path, passes: int = 0) -> None:
    """
    逻辑擦除优先保证稳定性；若 passes > 0 且是常规文件，则尝试覆盖后删除。
    注意：SSD / CoW 文件系统不保证物理擦除，生产安全依赖磁盘加密。
    """
    if not path.exists() or not path.is_file():
        return
    try:
        if passes > 0:
            size = path.stat().st_size
            # 仅对 <= 256MB 文件做覆盖，避免大文件拖垮 I/O
            if 0 < size <= 256 * 1024 * 1024:
                with open(path, "r+b", buffering=0) as f:
                    for i in range(passes):
                        f.seek(0)
                        if i % 2 == 0:
                            chunk = os.urandom(min(size, 1024 * 1024))
                            remain = size
                            while remain > 0:
                                n = min(len(chunk), remain)
                                f.write(chunk[:n])
                                remain -= n
                        else:
                            f.write(b"\x00" * min(size, 1024 * 1024))
                            remain = size - min(size, 1024 * 1024)
                            while remain > 0:
                                n = min(1024 * 1024, remain)
                                f.write(b"\x00" * n)
                                remain -= n
                        f.flush()
                        os.fsync(f.fileno())
        path.unlink(missing_ok=True)
    except Exception:
        safe_unlink(path)


def secure_rmtree(path: Path) -> None:
    try:
        if not path.exists():
            return
        if not path.is_dir():
            secure_delete_file(path, Config.SECURE_DELETE_PASSES)
            return
        # 优先安全删除文件，再删目录
        for p in path.rglob("*"):
            if p.is_file():
                secure_delete_file(p, Config.SECURE_DELETE_PASSES)
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)




def acquire_job_lease(job_id: str) -> bool:
    """跨进程/跨 worker 的轻量互斥锁。"""
    lock_path = LOCK_ROOT / f"{job_id}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8", errors="ignore"))
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return False


def release_job_lease(job_id: str) -> None:
    safe_unlink(LOCK_ROOT / f"{job_id}.lock")

def valid_upload_name(filename: str) -> bool:
    ext = Path(filename.lower()).suffix
    return ext in Config.ALLOWED_EXT


def safe_json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        x = raw.strip()
        if not x:
            return default
        try:
            return json.loads(x)
        except Exception:
            return default
    return default


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def boolish(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def srt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    hh, ms = divmod(ms, 3600000)
    mm, ms = divmod(ms, 60000)
    ss, ms = divmod(ms, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def run_cmd(cmd: List[str], timeout: int, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True, timeout=timeout)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        timeout=30,
    ).strip()
    return float(out)


def normalize_to_wav(input_path: Path, output_wav: Path) -> None:
    ensure_parent(output_wav)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ],
        timeout=900,
    )


# -----------------------------
# 元数据持久化
# -----------------------------
def _snapshot_for_meta(j: Dict[str, Any]) -> Dict[str, Any]:
    snap = copy.deepcopy(j)
    logs = snap.get("logs", [])
    if len(logs) > Config.META_LOG_MAX_LINES:
        snap["logs"] = logs[-Config.META_LOG_MAX_LINES :]
    return snap


def save_meta(job_snapshot: Dict[str, Any]) -> None:
    job_id = job_snapshot.get("id")
    if not job_id:
        return
    path = META_ROOT / f"{job_id}.json"
    atomic_write_text(path, json.dumps(job_snapshot, ensure_ascii=False, indent=2))


def mark_meta_dirty(job_id: str) -> None:
    with META_DIRTY_LOCK:
        META_DIRTY.add(job_id)


def flush_meta_once(force_all: bool = False) -> int:
    ids: List[str]
    if force_all:
        with JOBS_LOCK:
            ids = list(JOBS.keys())
    else:
        with META_DIRTY_LOCK:
            if not META_DIRTY:
                return 0
            ids = list(META_DIRTY)
            META_DIRTY.clear()

    flushed = 0
    for jid in ids:
        j = get_job(jid)
        if not j:
            continue
        try:
            save_meta(_snapshot_for_meta(j))
            flushed += 1
        except Exception as e:
            app.logger.error(f"save meta failed for {jid}: {e}")
    return flushed


def meta_flush_loop() -> None:
    while not SHUTDOWN.is_set():
        try:
            flush_meta_once(force_all=False)
        except Exception:
            app.logger.error("meta_flush_loop error:\n" + traceback.format_exc())
        SHUTDOWN.wait(Config.META_FLUSH_INTERVAL_SECONDS)


# -----------------------------
# Job 管理
# -----------------------------
def init_job(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    now = ts()
    rec = {
        "id": job_id,
        "status": "queued",
        "progress": 0.0,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
        "last_heartbeat": now,
        "payload": payload,
        "logs": [],
        "log_seq": 0,
        "error": None,
        "result_path": None,
        "download_name": None,
        "downloaded_at": None,
        "cancel_requested": False,
    }
    with JOBS_LOCK:
        JOBS[job_id] = rec
    mark_meta_dirty(job_id)
    return rec


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with JOBS_LOCK:
        if job_id in JOBS:
            return JOBS[job_id]

    meta_file = META_ROOT / f"{job_id}.json"
    if meta_file.exists():
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            with JOBS_LOCK:
                JOBS[job_id] = data
            return data
        except Exception:
            return None
    return None


def update_job(job_id: str, **kwargs: Any) -> None:
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            return
        j.update(kwargs)
        j["updated_at"] = ts()
    mark_meta_dirty(job_id)


def touch_heartbeat(job_id: str) -> None:
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            return
        j["last_heartbeat"] = ts()
        j["updated_at"] = ts()
    mark_meta_dirty(job_id)


def append_log(job_id: str, message: str) -> None:
    message = str(message).replace("\r", " ").replace("\n", " ").strip()
    if not message:
        return
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            return
        j["log_seq"] += 1
        j["logs"].append({"seq": j["log_seq"], "ts": time.strftime("%H:%M:%S"), "msg": message})
        if len(j["logs"]) > Config.LOG_MAX_LINES:
            j["logs"] = j["logs"][-Config.LOG_MAX_LINES :]
        j["updated_at"] = ts()
        j["last_heartbeat"] = ts()
    mark_meta_dirty(job_id)


def set_status(job_id: str, status: str) -> None:
    now = ts()
    patch: Dict[str, Any] = {"status": status, "updated_at": now, "last_heartbeat": now}
    if status == "running":
        patch["started_at"] = now
    if status in {"done", "error", "cancelled"}:
        patch["finished_at"] = now
    update_job(job_id, **patch)


def set_progress(job_id: str, p: float) -> None:
    p = float(clamp(float(p), 0.0, 100.0))
    update_job(job_id, progress=p)


def set_error(job_id: str, msg: str) -> None:
    update_job(job_id, status="error", error=str(msg)[:4000], finished_at=ts(), last_heartbeat=ts())


def set_result(job_id: str, path: Path, download_name: str) -> None:
    update_job(
        job_id,
        result_path=str(path),
        download_name=download_name,
        status="done",
        progress=100.0,
        finished_at=ts(),
        last_heartbeat=ts(),
        error=None,
    )


def mark_downloaded(job_id: str) -> None:
    update_job(job_id, downloaded_at=ts())


def is_cancel_requested(job_id: str) -> bool:
    j = get_job(job_id)
    return bool(j and j.get("cancel_requested"))


# -----------------------------
# 鉴权
# -----------------------------
def _read_token_from_request() -> str:
    h = request.headers.get("X-API-Token", "").strip()
    if h:
        return h
    q = request.args.get("token", "").strip()
    if q:
        return q
    return ""


def require_api_auth() -> Optional[Tuple[Any, int]]:
    """返回 (response, status) 表示拦截；None 表示通过。"""
    if not Config.API_AUTH_TOKEN:
        return None
    got = _read_token_from_request()
    if not got or got != Config.API_AUTH_TOKEN:
        return jsonify({"ok": False, "error": "未授权"}), 401
    return None


# -----------------------------
# VAD 与切片（Silero VAD）
# -----------------------------
@dataclass
class SpeechSeg:
    start: float
    end: float

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)




def load_audio_16k_mono_for_vad(wav_path: Path) -> torch.Tensor:
    """
    优先使用 silero_vad.read_audio；若 torchaudio 后端不可用，则回退标准库 wave 读取。
    仅用于我们已标准化后的 16k/mono/wav 文件。
    """
    try:
        return read_audio(str(wav_path), sampling_rate=16000)
    except Exception:
        pass

    with wave.open(str(wav_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)

    if frame_count <= 0:
        return torch.zeros(0, dtype=torch.float32)

    raw_buf = bytearray(raw)
    if sample_width == 2:
        pcm = torch.frombuffer(raw_buf, dtype=torch.int16).to(torch.float32) / 32768.0
    elif sample_width == 1:
        pcm = (torch.frombuffer(raw_buf, dtype=torch.uint8).to(torch.float32) - 128.0) / 128.0
    elif sample_width == 4:
        pcm = torch.frombuffer(raw_buf, dtype=torch.int32).to(torch.float32) / 2147483648.0
    else:
        raise RuntimeError(f"不支持的 WAV 位深: {sample_width * 8} bit")

    if channels > 1:
        pcm = pcm.view(-1, channels).mean(dim=1)

    if sample_rate != 16000 and pcm.numel() > 0:
        pcm = torch.nn.functional.interpolate(
            pcm.view(1, 1, -1),
            size=max(1, int(round(pcm.numel() * 16000 / float(sample_rate)))),
            mode="linear",
            align_corners=False,
        ).view(-1)

    return pcm.contiguous()

def detect_speech_segments(wav_path: Path, vad_options: Dict[str, Any]) -> Tuple[List[SpeechSeg], float, int]:
    """
    返回: (segments, total_duration, split_count)
    """
    total_dur = ffprobe_duration(wav_path)
    if total_dur <= 0.05:
        return [], 0.0, 0

    threshold = clamp(float(vad_options.get("vad_threshold", Config.SILERO_VAD_THRESHOLD)), 0.1, 0.95)
    min_silence_ms = int(clamp(float(vad_options.get("vad_min_silence_ms", Config.SILERO_MIN_SILENCE_MS)), 50, 3000))
    min_speech_ms = int(clamp(float(vad_options.get("vad_min_speech_ms", Config.SILERO_MIN_SPEECH_MS)), 50, 3000))
    speech_pad_ms = int(clamp(float(vad_options.get("vad_speech_pad_ms", Config.SILERO_SPEECH_PAD_MS)), 0, 1000))

    wav_tensor = load_audio_16k_mono_for_vad(wav_path)
    with torch.inference_mode():
        speech_ts = get_speech_timestamps(
            wav_tensor,
            SILERO_MODEL,
            threshold=threshold,
            sampling_rate=16000,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )

    pairs: List[Tuple[float, float]] = []
    for item in speech_ts:
        s = max(0.0, float(item.get("start", 0)) / 16000.0)
        e = min(total_dur, float(item.get("end", 0)) / 16000.0)
        if e > s:
            pairs.append((s, e))

    # 模型没检出语音时，回退整段，避免任务直接空失败
    if not pairs:
        pairs = [(0.0, total_dur)]

    # 去掉极短段
    filtered = [SpeechSeg(max(0.0, s), min(total_dur, e)) for s, e in pairs if (e - s) >= Config.MIN_SEGMENT_SECONDS]
    if not filtered:
        filtered = [SpeechSeg(0.0, total_dur)]

    # 长段强制切分
    out: List[SpeechSeg] = []
    split_count = 0
    for seg in filtered:
        if seg.dur <= Config.MAX_SEGMENT_SECONDS:
            out.append(seg)
            continue
        cur = seg.start
        while cur < seg.end - 0.05:
            nxt = min(cur + Config.MAX_SEGMENT_SECONDS, seg.end)
            out.append(SpeechSeg(cur, nxt))
            if nxt < seg.end:
                split_count += 1
            cur = nxt

    return out, total_dur, split_count


def vad_presets() -> Dict[str, Dict[str, Any]]:
    # 三套场景预设：通用 / ASMR / 混合
    return {
        "general": {
            "label": "通用（会议/视频/播客）",
            "vad_threshold": 0.55,
            "vad_min_silence_ms": 420,
            "vad_min_speech_ms": 240,
            "vad_speech_pad_ms": 110,
            "desc": "抑制碎段，适合普通语速与背景噪声。",
        },
        "asmr": {
            "label": "ASMR（低能量耳语）",
            "vad_threshold": 0.35,
            "vad_min_silence_ms": 300,
            "vad_min_speech_ms": 140,
            "vad_speech_pad_ms": 180,
            "desc": "提高弱语音召回，减少耳语漏检。",
        },
        "mixed": {
            "label": "混合（ASMR + 通用）",
            "vad_threshold": 0.45,
            "vad_min_silence_ms": 360,
            "vad_min_speech_ms": 180,
            "vad_speech_pad_ms": 140,
            "desc": "在召回与误检间折中，适合混合素材。",
        },
    }


def resolve_vad_options(options: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    presets = vad_presets()
    preset = str(options.get("vad_preset", Config.VAD_PRESET_DEFAULT) or Config.VAD_PRESET_DEFAULT).strip().lower()

    # 向后兼容旧参数：vad_profile
    legacy_profile = str(options.get("vad_profile", "")).strip().lower()
    if legacy_profile == "asmr":
        preset = "asmr"
    elif legacy_profile in {"balanced", "general"}:
        preset = "general"

    if preset not in presets:
        preset = "general"

    base = presets[preset]
    out = {
        "vad_threshold": clamp(float(options.get("vad_threshold", base["vad_threshold"])), 0.1, 0.95),
        "vad_min_silence_ms": int(clamp(float(options.get("vad_min_silence_ms", base["vad_min_silence_ms"])), 50, 3000)),
        "vad_min_speech_ms": int(clamp(float(options.get("vad_min_speech_ms", base["vad_min_speech_ms"])), 50, 3000)),
        "vad_speech_pad_ms": int(clamp(float(options.get("vad_speech_pad_ms", base["vad_speech_pad_ms"])), 0, 1000)),
    }

    # 向后兼容旧参数：utterance_split（秒）-> min_silence_ms
    if "utterance_split" in options:
        try:
            ms = int(clamp(float(options.get("utterance_split")) * 1000.0, 50, 3000))
            out["vad_min_silence_ms"] = ms
        except Exception:
            pass

    return preset, out


def optimize_segments_for_transcription(
    segments: List[SpeechSeg],
    min_transcribe_seconds: float,
    merge_gap_seconds: float,
    max_segment_seconds: float,
) -> Tuple[List[SpeechSeg], int, int]:
    """
    通过“短段就地合并”降低空白/极短片段触发 EMPTY_TRANSCRIPT 的概率。
    返回: (优化后片段, 合并次数, 丢弃次数)
    """
    if not segments:
        return [], 0, 0

    min_dur = clamp(float(min_transcribe_seconds), 0.2, 2.0)
    merge_gap = clamp(float(merge_gap_seconds), 0.0, 1.0)
    max_dur = max(2.0, float(max_segment_seconds))

    src = sorted(segments, key=lambda x: (x.start, x.end))
    out: List[SpeechSeg] = []
    merged_count = 0
    dropped_count = 0

    for seg in src:
        seg = SpeechSeg(seg.start, seg.end)
        if seg.dur >= min_dur:
            out.append(seg)
            continue

        merged = False
        # 优先向后合并：短段 + 紧邻后段
        if out:
            prev = out[-1]
            gap_prev = max(0.0, seg.start - prev.end)
            if gap_prev <= merge_gap and (seg.end - prev.start) <= max_dur:
                out[-1] = SpeechSeg(prev.start, max(prev.end, seg.end))
                merged_count += 1
                merged = True

        if not merged:
            # 保留单独短段的最后兜底：避免全部丢弃导致段空
            if seg.dur >= max(0.22, min_dur * 0.6):
                out.append(seg)
            else:
                dropped_count += 1

    if not out and src:
        out = [src[0]]

    return out, merged_count, dropped_count


def extract_segment_wav(full_wav: Path, out_wav: Path, start: float, end: float) -> None:
    duration = max(0.0, end - start)
    if duration < 0.01:
        raise ValueError(f"segment too short: start={start:.6f}, end={end:.6f}")

    ensure_parent(out_wav)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(full_wav),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-af",
            "dynaudnorm=p=0.9:s=5",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(out_wav),
        ],
        timeout=180,
    )


# -----------------------------
# 转写与文本质量优化
# -----------------------------
def normalize_transcript_text(text: str, language: str = "auto", model: str = "") -> str:
    if not text:
        return ""
    x = html.unescape(str(text))
    x = x.replace("\u3000", " ")
    x = re.sub(r"[\t\r\f\v]+", " ", x)
    x = re.sub(r"\n+", " ", x)
    x = re.sub(r"\s{2,}", " ", x).strip()

    # 修复 CJK 之间被错误插空格的问题
    cjk = r"\u4e00-\u9fff\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af"
    x = re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", x)

    # 清理中英文标点前后空格
    x = re.sub(r"\s+([,，。！？!?:：；;])", r"\1", x)
    x = re.sub(r"([\(（\[【{])\s+", r"\1", x)
    x = re.sub(r"\s+([\)）\]】}])", r"\1", x)

    # 降噪：大量重复标点折叠
    x = re.sub(r"([!?！？。.,，])\1{2,}", r"\1\1", x)

    model_l = (model or "").lower()

    # 若模型输出全部是按字空格（典型 whisper/kotoba 在 CJK 场景异常），再做一次紧缩
    if language in {"zh", "ja", "auto"} or "whisper" in model_l or "kotoba" in model_l:
        x = re.sub(rf"(?<=[{cjk}])\s+(?=[{cjk}])", "", x)
        x = re.sub(rf"(?<=[{cjk}])\s+(?=[，。！？、；：])", "", x)
        x = re.sub(rf"(?<=[，。！？、；：])\s+(?=[{cjk}])", "", x)

    return x.strip()


def _split_by_punctuation(text: str, language: str = "auto") -> List[str]:
    if not text:
        return []
    # 按句末标点切开，保留标点（兼容中英日）
    parts = re.split(r"(?<=[。！？!?；;…\.!?])\s+", text)
    # 英文长句再按逗号/分号弱切，减少单行过长
    if language == "en":
        tmp: List[str] = []
        for p in parts:
            p = p.strip()
            if len(p) > 72 and re.search(r",|;", p):
                tmp.extend([x for x in re.split(r"(?<=[,;])\s+", p) if x.strip()])
            else:
                tmp.append(p)
        parts = tmp
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out if out else [text]


def _char_budget(language: str, model: str = "") -> int:
    model_l = (model or "").lower()
    if language == "ja":
        return 20
    if language == "zh":
        return 24
    if language == "auto" and ("kotoba" in model_l or "whisper" in model_l):
        return 22
    return 42


def split_text_for_srt(text: str, language: str, max_chars: Optional[int] = None, model: str = "") -> List[str]:
    if not text:
        return []
    budget = max_chars or _char_budget(language, model=model)
    budget = max(10, min(100, budget))

    sentences = _split_by_punctuation(text, language=language)
    lines: List[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        c = cur.strip()
        if c:
            lines.append(c)
        cur = ""

    for s in sentences:
        s = s.strip()
        if not s:
            continue

        # 特长句硬切
        if len(s) > budget * 1.8:
            flush()
            start = 0
            while start < len(s):
                lines.append(s[start : start + budget])
                start += budget
            continue

        if not cur:
            cur = s
            continue

        candidate = f"{cur} {s}" if re.search(r"[A-Za-z0-9]$", cur) else f"{cur}{s}"
        if len(candidate) <= budget:
            cur = candidate
        else:
            flush()
            cur = s

    flush()

    # 合并过短行
    merged: List[str] = []
    for line in lines:
        if not merged:
            merged.append(line)
            continue
        if len(line) < max(4, budget // 5) and len(merged[-1]) + len(line) + 1 <= budget + 6:
            sep = " " if re.search(r"[A-Za-z0-9]$", merged[-1]) else ""
            merged[-1] += sep + line
        else:
            merged.append(line)
    return merged


def allocate_line_times(seg_start: float, seg_end: float, lines: List[str]) -> List[Tuple[float, float, str]]:
    if not lines:
        return []
    dur = max(0.2, seg_end - seg_start)
    if len(lines) == 1:
        return [(seg_start, seg_end, lines[0])]

    weights = [max(1, len(x)) for x in lines]
    total_w = sum(weights)
    t = seg_start
    cues: List[Tuple[float, float, str]] = []

    for i, line in enumerate(lines):
        if i == len(lines) - 1:
            nxt = seg_end
        else:
            piece = dur * (weights[i] / total_w)
            piece = max(0.3, piece)
            nxt = min(seg_end, t + piece)
        cues.append((t, nxt, line))
        t = nxt

    # 纠正可能的重叠/倒序
    fixed: List[Tuple[float, float, str]] = []
    prev_end = seg_start
    for s, e, txt in cues:
        s = max(s, prev_end)
        e = max(e, s + 0.18)
        fixed.append((s, e, txt))
        prev_end = e

    # 最后一条强行贴合段尾
    if fixed:
        s, _, txt = fixed[-1]
        fixed[-1] = (s, max(s + 0.18, seg_end), txt)
    return fixed


def deepgram_model_defaults(model: str) -> Dict[str, str]:
    """
    基于官方可用参数做保守默认值：
    - nova-2/3: 对话/通用场景，保留 smart_format + punctuate + utterances
    - whisper-large: 以可读字幕优先，保留 punctuate/utterances，smart_format 默认关闭以减少格式化副作用
    所有值都允许被 options 显式覆盖。
    """
    m = (model or "").lower()
    base = {
        "smart_format": "true",
        "punctuate": "true",
        "diarize": "false",
        "paragraphs": "false",
        "numerals": "false",
        "profanity_filter": "false",
        "utterances": "true",
        "filler_words": "false",
    }
    if m == "whisper-large":
        base["smart_format"] = "false"
    return base

def transcribe_with_deepgram(seg_file: Path, model: str, language: str, options: Dict[str, Any]) -> Tuple[bool, str, str, int]:
    if not Config.DEEPGRAM_API_KEY:
        return False, "", "DEEPGRAM_API_KEY missing", 0

    defaults = deepgram_model_defaults(model)
    params = {"model": model}
    for k, v in defaults.items():
        params[k] = str(boolish(options.get(k), v == "true")).lower()
    utt_split = options.get("utterance_split")
    try:
        if utt_split is not None and str(utt_split).strip() != "":
            v = clamp(float(utt_split), 0.1, 5.0)
            params["utt_split"] = f"{v:.2f}"
    except Exception:
        pass

    keywords = options.get("keywords")
    if isinstance(keywords, list) and keywords:
        cleaned = [str(x).strip() for x in keywords if str(x).strip()]
        if cleaned:
            params["keywords"] = cleaned

    if language == "auto":
        params["detect_language"] = "true"
    else:
        params["language"] = language

    headers = {
        "Authorization": f"Token {Config.DEEPGRAM_API_KEY}",
        # Deepgram 预录音频接口支持直接发送音频二进制，显式声明类型更稳妥。
        "Content-Type": "audio/wav",
    }

    with open(seg_file, "rb") as f:
        resp = SESSION.post(
            dg_url("/listen"),
            params=params,
            headers=headers,
            data=f,
            timeout=Config.REQUEST_TIMEOUT_SECONDS,
        )

    status = resp.status_code
    if status != 200:
        msg = (resp.text or "")[:180].replace("\n", " ")
        return False, "", f"DG_ERR_{status}: {msg}", status

    try:
        data = resp.json()
        txt = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        txt = (txt or "").strip()
        if not txt:
            return False, "", "EMPTY_TRANSCRIPT", status
        return True, txt, "", status
    except Exception:
        return False, "", "DG_JSON_PARSE_ERR", status


def transcribe_with_hf(seg_file: Path) -> Tuple[bool, str, str, int]:
    if not Config.HF_TOKEN:
        return False, "", "HF_TOKEN missing", 0

    headers = {
        "Authorization": f"Bearer {Config.HF_TOKEN}",
        "Content-Type": "audio/wav",
    }
    params = {"wait_for_model": "true"}
    with open(seg_file, "rb") as f:
        resp = SESSION.post(
            Config.HF_KOTOBA_URL,
            headers=headers,
            params=params,
            data=f,
            timeout=max(120, Config.REQUEST_TIMEOUT_SECONDS),
        )

    status = resp.status_code
    if status != 200:
        msg = (resp.text or "")[:180].replace("\n", " ")
        return False, "", f"HF_ERR_{status}: {msg}", status

    try:
        data = resp.json()
        txt = (data.get("text") or "").strip()
        if not txt:
            return False, "", "HF_EMPTY_TRANSCRIPT", status
        return True, txt, "", status
    except Exception:
        return False, "", "HF_JSON_PARSE_ERR", status


@dataclass
class SegmentResult:
    ok: bool
    idx: int
    start: float
    end: float
    text: str
    error: Optional[str] = None
    code: int = 0


def _empty_retry_window(seg: SpeechSeg) -> Tuple[float, float]:
    pad = 0.22 if seg.dur < 1.2 else (0.35 if seg.dur < 3.0 else 0.50)
    retry_start = max(0.0, seg.start - pad)
    retry_end = max(retry_start + 0.02, seg.end + pad)
    return retry_start, retry_end


def transcribe_task(
    job_id: str,
    idx: int,
    seg: SpeechSeg,
    full_wav: Path,
    model: str,
    language: str,
    options: Dict[str, Any],
) -> SegmentResult:
    seg_dir = TMP_ROOT / job_id / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    seg_file = seg_dir / f"seg_{idx:05d}.wav"

    if is_cancel_requested(job_id):
        return SegmentResult(False, idx, seg.start, seg.end, "", "CANCELLED")
    if seg.dur < 0.01:
        return SegmentResult(False, idx, seg.start, seg.end, "", "INVALID_SEGMENT_DURATION")

    try:
        extract_segment_wav(full_wav, seg_file, seg.start, seg.end)

        if "kotoba" in model:
            ok, txt, err, code = transcribe_with_hf(seg_file)
        else:
            ok, txt, err, code = transcribe_with_deepgram(seg_file, model, language, options)
            # 对 EMPTY_TRANSCRIPT 做更稳健重试：扩窗 +（若指定语言）自动语言兜底。
            if (not ok) and err == "EMPTY_TRANSCRIPT":
                retry_start, retry_end = _empty_retry_window(seg)
                extract_segment_wav(full_wav, seg_file, retry_start, retry_end)

                retry_lang = "auto" if language != "auto" else language
                ok, txt, err, code = transcribe_with_deepgram(seg_file, model, retry_lang, options)

        if ok:
            txt = normalize_transcript_text(txt, language, model=model)
            if not txt:
                return SegmentResult(False, idx, seg.start, seg.end, "", "EMPTY_AFTER_NORMALIZE", code)
            return SegmentResult(True, idx, seg.start, seg.end, txt, None, code)
        return SegmentResult(False, idx, seg.start, seg.end, "", err or "TRANSCRIBE_FAIL", code)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e))
        msg = re.sub(r"\s+", " ", msg)[:180]
        return SegmentResult(False, idx, seg.start, seg.end, "", f"FFMPEG_ERR: {msg}")
    except Exception as e:
        return SegmentResult(False, idx, seg.start, seg.end, "", f"EXC: {str(e)[:180]}")
    finally:
        safe_unlink(seg_file)


def build_srt(results: List[SegmentResult], language: str, model: str = "") -> str:
    # 结果按时间排序
    results = sorted([r for r in results if r.ok and r.text], key=lambda x: (x.start, x.end, x.idx))

    cues: List[Tuple[float, float, str]] = []
    for r in results:
        lines = split_text_for_srt(r.text, language=language, model=model)
        parts = allocate_line_times(r.start, r.end, lines)
        cues.extend(parts)

    # 最终兜底：去空、去重叠
    final_cues: List[Tuple[float, float, str]] = []
    prev_end = 0.0
    for s, e, txt in cues:
        txt = txt.strip()
        if not txt:
            continue
        s = max(s, prev_end)
        if e <= s:
            e = s + 0.2
        final_cues.append((s, e, txt))
        prev_end = e

    # 合并紧邻且文本相同的 cue，避免视觉上“抖动”式分裂。
    compact_cues: List[Tuple[float, float, str]] = []
    for s, e, txt in final_cues:
        if compact_cues:
            ps, pe, ptxt = compact_cues[-1]
            if txt == ptxt and s - pe <= 0.12:
                compact_cues[-1] = (ps, max(pe, e), ptxt)
                continue
        compact_cues.append((s, e, txt))

    lines_out: List[str] = []
    for i, (s, e, txt) in enumerate(compact_cues, 1):
        lines_out.append(f"{i}\n{srt_ts(s)} --> {srt_ts(e)}\n{txt}\n")

    return "\n".join(lines_out).strip() + "\n"


# -----------------------------
# 核心任务流程
# -----------------------------
def process_job(job_id: str) -> None:
    j = get_job(job_id)
    if not j:
        return

    if not acquire_job_lease(job_id):
        append_log(job_id, "⏭️ 检测到其他 Worker 正在处理该任务，当前实例跳过")
        return

    payload = j.get("payload") or {}
    file_path = Path(payload.get("file_path", ""))
    model = payload.get("model", Config.DEFAULT_MODEL)
    language = payload.get("language", "auto")
    options = payload.get("options") or {}

    if not file_path.exists():
        set_error(job_id, "上传文件不存在或已被清理")
        append_log(job_id, "❌ 上传文件缺失")
        return

    if is_cancel_requested(job_id):
        set_status(job_id, "cancelled")
        append_log(job_id, "🛑 任务已取消")
        return

    try:
        set_status(job_id, "running")
        set_progress(job_id, 1)
        append_log(job_id, f"🚀 任务启动 | 模型: {model} | 语言: {language}")

        wav = TMP_ROOT / job_id / "normalized.wav"
        normalize_to_wav(file_path, wav)
        touch_heartbeat(job_id)
        set_progress(job_id, 8)
        append_log(job_id, "✅ 音频标准化完成 (16k/mono/wav)")

        vad_preset, vad_options = resolve_vad_options(options)
        vad_threshold = float(vad_options["vad_threshold"])
        vad_min_silence_ms = int(vad_options["vad_min_silence_ms"])
        vad_min_speech_ms = int(vad_options["vad_min_speech_ms"])
        vad_speech_pad_ms = int(vad_options["vad_speech_pad_ms"])

        segments, total_dur, split_count = detect_speech_segments(wav, vad_options=vad_options)
        touch_heartbeat(job_id)
        if not segments:
            raise RuntimeError("未检测到有效语音片段")

        min_transcribe = options.get("min_transcribe_segment_seconds", Config.MIN_TRANSCRIBE_SEGMENT_SECONDS)
        try:
            min_transcribe_sec = clamp(float(min_transcribe), 0.2, 2.0)
        except Exception:
            min_transcribe_sec = Config.MIN_TRANSCRIBE_SEGMENT_SECONDS

        merge_gap = options.get("short_segment_merge_gap_seconds", Config.SHORT_SEGMENT_MERGE_GAP_SECONDS)
        try:
            merge_gap_sec = clamp(float(merge_gap), 0.0, 1.0)
        except Exception:
            merge_gap_sec = Config.SHORT_SEGMENT_MERGE_GAP_SECONDS

        segments, merged_short, dropped_short = optimize_segments_for_transcription(
            segments,
            min_transcribe_seconds=min_transcribe_sec,
            merge_gap_seconds=merge_gap_sec,
            max_segment_seconds=Config.MAX_SEGMENT_SECONDS,
        )

        speech_sum = sum(s.dur for s in segments)
        ratio = (speech_sum / total_dur * 100.0) if total_dur > 0 else 0.0
        append_log(
            job_id,
            f"🎙️ Silero VAD 完成: {len(segments)} 段 | 分裂 {split_count} 次 | 有声占比 {ratio:.1f}% | preset={vad_preset} threshold={vad_threshold:.2f} min_silence={vad_min_silence_ms}ms min_speech={vad_min_speech_ms}ms pad={vad_speech_pad_ms}ms | 合并短段 {merged_short} | 丢弃超短 {dropped_short}",
        )
        set_progress(job_id, 14)

        if is_cancel_requested(job_id):
            set_status(job_id, "cancelled")
            append_log(job_id, "🛑 任务已取消")
            return

        results: List[SegmentResult] = []
        fail_count = 0
        empty_count = 0
        total = len(segments)

        with ThreadPoolExecutor(max_workers=Config.CONCURRENCY) as executor:
            future_map = {
                executor.submit(transcribe_task, job_id, i, seg, wav, model, language, options): i
                for i, seg in enumerate(segments)
            }
            done = 0
            for fut in as_completed(future_map):
                done += 1
                touch_heartbeat(job_id)

                if is_cancel_requested(job_id):
                    append_log(job_id, "🛑 检测到取消请求，正在收尾")
                    # 不再等待剩余 future 的结果
                    break

                try:
                    r = fut.result()
                except Exception as e:
                    idx = future_map[fut]
                    r = SegmentResult(False, idx, 0.0, 0.0, "", f"FUTURE_EXC: {str(e)[:120]}")

                if r.ok:
                    results.append(r)
                else:
                    if r.error in EMPTY_SEGMENT_ERRORS:
                        empty_count += 1
                    else:
                        fail_count += 1
                        if r.error and r.error not in {"CANCELLED"}:
                            append_log(job_id, f"⚠️ 片段#{r.idx} 失败: {r.error}")

                p = 14 + (80 * done / max(1, total))
                set_progress(job_id, p)

        if is_cancel_requested(job_id):
            set_status(job_id, "cancelled")
            append_log(job_id, "🛑 任务已取消")
            return

        if not results:
            raise RuntimeError(f"转录全量失败（失败段: {fail_count + empty_count}）")

        if empty_count > 0:
            append_log(job_id, f"ℹ️ 空转写片段: {empty_count} 段（多为静音/呼吸/噪声），已自动忽略")

        if fail_count > 0:
            append_log(job_id, f"ℹ️ 部分片段失败: {fail_count} 段，已自动跳过")

        srt = build_srt(results, language=language, model=model)
        out_path = OUTPUTS_ROOT / f"{job_id}.srt"
        atomic_write_text(out_path, srt)

        original_name = payload.get("original_name", "subtitle.srt")
        download_name = Path(original_name).stem + ".srt"
        set_result(job_id, out_path, download_name)
        append_log(job_id, "✅ 任务完成，SRT 已生成")

    except Exception as e:
        err = str(e)
        set_error(job_id, err)
        append_log(job_id, f"❌ 任务失败: {err}")
        app.logger.error("process_job failed:\n" + traceback.format_exc())
    finally:
        # 清理临时目录
        secure_rmtree(TMP_ROOT / job_id)
        release_job_lease(job_id)
        mark_meta_dirty(job_id)


# -----------------------------
# Worker / Cleanup
# -----------------------------
def worker_loop(worker_idx: int) -> None:
    name = f"job-worker-{worker_idx}"
    app.logger.info(f"{name} started")
    while not SHUTDOWN.is_set():
        try:
            job_id = JOB_QUEUE.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            j = get_job(job_id)
            if not j:
                continue
            if j.get("status") not in {"queued", "running"}:
                continue
            if j.get("cancel_requested"):
                set_status(job_id, "cancelled")
                append_log(job_id, "🛑 队列中取消")
                continue
            process_job(job_id)
        except Exception:
            app.logger.error(f"{name} fatal while processing {job_id}:\n{traceback.format_exc()}")
            set_error(job_id, "Worker 异常终止")
        finally:
            JOB_QUEUE.task_done()


def _delete_job_artifacts(job_id: str) -> None:
    release_job_lease(job_id)
    secure_rmtree(UPLOADS_ROOT / job_id)
    secure_rmtree(TMP_ROOT / job_id)
    srt = OUTPUTS_ROOT / f"{job_id}.srt"
    if srt.exists():
        secure_delete_file(srt, Config.SECURE_DELETE_PASSES)
    safe_unlink(META_ROOT / f"{job_id}.json")
    with JOBS_LOCK:
        JOBS.pop(job_id, None)


def cleanup_loop() -> None:
    while not SHUTDOWN.is_set():
        try:
            if not Config.AUTO_CLEANUP_ENABLED:
                SHUTDOWN.wait(30)
                continue

            now = ts()
            with JOBS_LOCK:
                ids = list(JOBS.keys())

            for jid in ids:
                j = get_job(jid)
                if not j:
                    continue

                status = j.get("status", "queued")
                updated_at = float(j.get("updated_at") or now)
                heartbeat = float(j.get("last_heartbeat") or updated_at)
                age = now - updated_at
                hb_age = now - heartbeat

                # 孤儿任务判定：queued/running 长时间无心跳
                if status in {"queued", "running"} and hb_age > Config.ORPHAN_RETENTION_SECONDS:
                    append_log(jid, "⚠️ 任务心跳超时，已标记为错误")
                    set_error(jid, "任务心跳超时（可能进程异常中断）")
                    continue

                should_delete = False

                if status == "done":
                    if Config.AUTO_CLEANUP_AFTER_DOWNLOAD and j.get("downloaded_at"):
                        down_age = now - float(j.get("downloaded_at") or now)
                        if down_age >= Config.DOWNLOAD_GRACE_SECONDS:
                            should_delete = True
                    elif age >= Config.DONE_RETENTION_SECONDS:
                        should_delete = True
                elif status in {"error", "cancelled"}:
                    if age >= Config.ERROR_RETENTION_SECONDS:
                        should_delete = True

                if should_delete:
                    _delete_job_artifacts(jid)

        except Exception:
            app.logger.error("cleanup_loop error:\n" + traceback.format_exc())

        SHUTDOWN.wait(Config.CLEANUP_INTERVAL_SECONDS)


# -----------------------------
# API 路由
# -----------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        app_title=Config.APP_TITLE,
        model_jp="kotoba-tech/kotoba-whisper-v2.2",
        default_model=Config.DEFAULT_MODEL,
        auth_enabled=bool(Config.API_AUTH_TOKEN),
    )


@app.route("/api/health")
def api_health():
    # health 允许无鉴权，方便容器探针
    with JOBS_LOCK:
        queued = sum(1 for x in JOBS.values() if x.get("status") == "queued")
        running = sum(1 for x in JOBS.values() if x.get("status") == "running")
    return jsonify(
        {
            "ok": True,
            "app": Config.APP_TITLE,
            "queued": queued,
            "running": running,
            "workers": Config.JOB_WORKERS,
            "segment_concurrency": Config.CONCURRENCY,
            "auth": bool(Config.API_AUTH_TOKEN),
            "version": "v6.0",
        }
    )


@app.route("/api/config")
def api_config():
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail
    return jsonify(
        {
            "ok": True,
            "max_upload_mb": Config.MAX_UPLOAD_MB,
            "default_model": Config.DEFAULT_MODEL,
            "supported_lang": sorted(Config.SUPPORTED_LANG),
            "supported_models": sorted(Config.SUPPORTED_MODELS),
            "vad_defaults": {
                "engine": "silero-vad",
                "vad_threshold": Config.SILERO_VAD_THRESHOLD,
                "vad_min_silence_ms": Config.SILERO_MIN_SILENCE_MS,
                "vad_min_speech_ms": Config.SILERO_MIN_SPEECH_MS,
                "vad_speech_pad_ms": Config.SILERO_SPEECH_PAD_MS,
                "vad_preset": Config.VAD_PRESET_DEFAULT if Config.VAD_PRESET_DEFAULT in vad_presets() else "general",
                "vad_presets": vad_presets(),
                "min_transcribe_segment_seconds": Config.MIN_TRANSCRIBE_SEGMENT_SECONDS,
                "short_segment_merge_gap_seconds": Config.SHORT_SEGMENT_MERGE_GAP_SECONDS,
            },
            "auth_enabled": bool(Config.API_AUTH_TOKEN),
        }
    )


@app.route("/api/start", methods=["POST"])
def api_start():
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail

    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "无文件上传"}), 400

    lang = request.form.get("language", "auto").strip()
    model = request.form.get("model", Config.DEFAULT_MODEL).strip()
    options = safe_json_loads(request.form.get("options", "{}"), {})

    if lang not in Config.SUPPORTED_LANG:
        return jsonify({"ok": False, "error": f"不支持的语言: {lang}"}), 400
    if model not in Config.SUPPORTED_MODELS:
        return jsonify({"ok": False, "error": f"不支持的模型: {model}"}), 400

    if "kotoba" not in model and not Config.DEEPGRAM_API_KEY:
        return jsonify({"ok": False, "error": "DEEPGRAM_API_KEY 未配置"}), 400

    original_name = (f.filename or "upload.bin").strip() or "upload.bin"
    safe_name = secure_filename(original_name)
    if not safe_name:
        # 兜底名
        safe_name = f"upload_{uuid.uuid4().hex[:10]}.bin"

    # 扩展名检查（仅警告不强拒绝，保持兼容）
    if not valid_upload_name(safe_name):
        app.logger.warning(f"unexpected extension upload: {safe_name}")

    job_id = uuid.uuid4().hex
    upload_dir = UPLOADS_ROOT / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / safe_name

    try:
        f.save(str(input_path))
    except Exception as e:
        return jsonify({"ok": False, "error": f"保存上传文件失败: {e}"}), 500

    payload = {
        "file_path": str(input_path),
        "language": lang,
        "model": model,
        "original_name": original_name,
        "options": options if isinstance(options, dict) else {},
    }
    init_job(job_id, payload)
    append_log(job_id, "📦 文件上传完成，任务已入队")
    JOB_QUEUE.put(job_id)

    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail

    j = get_job(job_id)
    if not j:
        return jsonify({"ok": False, "error": "任务不存在"}), 404

    since_raw = request.args.get("since", "0")
    try:
        since = int(since_raw)
    except Exception:
        since = 0

    logs = j.get("logs") or []
    new_logs = [x for x in logs if int(x.get("seq", 0)) > since]
    next_since = int(logs[-1].get("seq", since)) if logs else since

    return jsonify(
        {
            "ok": True,
            "status": j.get("status"),
            "progress": float(j.get("progress", 0.0)),
            "logs": new_logs,
            "next_since": next_since,
            "download_url": f"/api/download/{job_id}" if j.get("result_path") else None,
            "error": j.get("error"),
            "cancel_requested": bool(j.get("cancel_requested")),
        }
    )


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id: str):
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail

    j = get_job(job_id)
    if not j:
        return jsonify({"ok": False, "error": "任务不存在"}), 404

    status = j.get("status")
    if status in {"done", "error", "cancelled"}:
        return jsonify({"ok": True, "status": status, "message": "任务已结束"})

    update_job(job_id, cancel_requested=True)
    append_log(job_id, "🛑 已收到取消请求")

    # 对 queued 任务可直接标记，running 则由 worker 尽快收敛
    j2 = get_job(job_id) or {}
    if j2.get("status") == "queued":
        set_status(job_id, "cancelled")
    return jsonify({"ok": True, "status": (get_job(job_id) or {}).get("status", "unknown")})


@app.route("/api/download/<job_id>")
def api_download(job_id: str):
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail

    j = get_job(job_id)
    if not j:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if j.get("status") != "done":
        return jsonify({"ok": False, "error": "结果未就绪"}), 404

    p = Path(j.get("result_path") or "")
    if not p.exists():
        return jsonify({"ok": False, "error": "结果文件不存在"}), 404

    mark_downloaded(job_id)
    return send_file(str(p), as_attachment=True, download_name=j.get("download_name") or "subtitle.srt")


@app.route("/api/balance")
def api_balance():
    auth_fail = require_api_auth()
    if auth_fail:
        return auth_fail

    if not Config.DEEPGRAM_API_KEY:
        return jsonify({"ok": False, "error": "DEEPGRAM_API_KEY 未配置"}), 400

    headers = {"Authorization": f"Token {Config.DEEPGRAM_API_KEY}"}
    project_id = request.args.get("project_id", "").strip()

    try:
        if not project_id:
            r = SESSION.get(dg_url("/projects"), headers=headers, timeout=20)
            if r.status_code != 200:
                return jsonify({"ok": False, "error": "上游鉴权失败", "status": r.status_code}), 401
            projects = (r.json() or {}).get("projects") or []
            if not projects:
                return jsonify({"ok": False, "error": "无可用项目"}), 404
            project_id = (projects[0] or {}).get("project_id") or ""
            if not project_id:
                return jsonify({"ok": False, "error": "项目 ID 缺失"}), 502

        b = SESSION.get(dg_url(f"/projects/{project_id}/balances"), headers=headers, timeout=20)
        if b.status_code != 200:
            return jsonify({"ok": False, "error": "上游响应异常", "status": b.status_code}), 502

        balances = (b.json() or {}).get("balances") or []
        total = sum(float(item.get("amount", 0) or 0) for item in balances)
        return jsonify({"ok": True, "total": total, "project_id": project_id})
    except Exception as e:
        return jsonify({"ok": False, "error": "服务器内部错误", "detail": str(e)}), 500


# -----------------------------
# 启动流程
# -----------------------------
def bootstrap() -> None:
    Config.print_info()

    # 1) 恢复历史任务档案
    loaded = 0
    for p in META_ROOT.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            jid = d.get("id")
            if not jid:
                continue
            with JOBS_LOCK:
                JOBS[jid] = d
            loaded += 1
        except Exception:
            continue

    if loaded:
        print(f"恢复历史任务: {loaded} 条")

    # 2) 把 queued/running 的历史任务重新入队（并由心跳机制兜底）
    requeue = 0
    with JOBS_LOCK:
        for jid, j in JOBS.items():
            if j.get("status") in {"queued", "running"} and not j.get("cancel_requested"):
                JOB_QUEUE.put(jid)
                requeue += 1
    if requeue:
        print(f"已重新入队任务: {requeue} 条")

    # 3) 后台线程
    threading.Thread(target=meta_flush_loop, daemon=True, name="meta-flush").start()
    threading.Thread(target=cleanup_loop, daemon=True, name="cleanup-loop").start()
    for i in range(Config.JOB_WORKERS):
        threading.Thread(target=worker_loop, args=(i,), daemon=True, name=f"worker-{i}").start()


bootstrap()


if __name__ == "__main__":
    host = _env_str("HOST", "0.0.0.0")
    port = _env_int("PORT", 7860, minimum=1, maximum=65535)
    debug = _env_bool("FLASK_DEBUG", False)
    app.run(host=host, port=port, debug=debug, threaded=True)
