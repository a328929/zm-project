FROM python:3.11-slim

# 1. 直接从官方镜像把 uv 那个文件拷过来（比 pip install uv 快得多）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装系统依赖（这一步没问题，保留）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tini \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

# 优先安装 CPU 版 PyTorch，避免默认源拉取体积更大的 CUDA 依赖
RUN uv pip install --system \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.8.0 torchaudio==2.8.0

# 其余依赖走默认源
RUN uv pip install --system -r requirements.txt

COPY . .

# 提前创建目录
RUN mkdir -p /app/jobs/uploads /app/jobs/tmp /app/jobs/outputs /app/jobs/meta

EXPOSE 7860

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "8", "-b", "0.0.0.0:7860", "app:app", "--timeout", "3600"]
