# Urai v3 — Production Dockerfile
# CPU build (default):
#   docker build -t urai:v3 .
#
# GPU build (NVIDIA CUDA):
#   docker build --build-arg BASE_IMAGE=nvidia/cuda:12.4.1-runtime-ubuntu22.04 \
#                --build-arg GGML_CUDA=ON -t urai:v3-gpu .
#
# Run:
#   docker run -p 8777:8777 \
#     -e URAI_MASTER_KEY=$(openssl rand -hex 32) \
#     -e URAI_MODEL=qwen3-4b \
#     -v urai-model:/app/model \
#     -v urai-data:/app/data \
#     urai:v3

ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG GGML_CUDA=OFF
ARG LLAMA_CPP_COMMIT=7049ff0cbeb1f5ead231de4522af6b75d8d773c0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update -qq && apt-get install -y -qq \
    build-essential cmake git curl \
    libcurl4-openssl-dev libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd -m -u 1000 -s /bin/bash urai
WORKDIR /app
COPY . /app
RUN chown -R urai:urai /app

# Build llama.cpp
RUN git init third_party/llama.cpp \
 && cd third_party/llama.cpp \
 && git remote add origin https://github.com/ggml-org/llama.cpp.git \
 && git fetch --depth 1 origin ${LLAMA_CPP_COMMIT} \
 && git checkout FETCH_HEAD \
 && cd /app \
 && cmake -S third_party/llama.cpp \
          -B third_party/llama.cpp/build \
          -DCMAKE_BUILD_TYPE=Release \
          -DGGML_NATIVE=OFF \
          -DGGML_CUDA=${GGML_CUDA} \
 && cmake --build third_party/llama.cpp/build \
          -j$(nproc) \
          --target llama-cli llama-bench llama-quantize llama-server \
 && rm -rf third_party/llama.cpp/.git

# Syntax-check all Python
RUN python3 -m py_compile jev/*.py \
 && chmod +x bin/urai bin/jev docker/entrypoint.sh

# Volumes for persistent data
VOLUME ["/app/model", "/app/out", "/app/data"]
EXPOSE 8777

# Switch to non-root
USER urai

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8777/health',timeout=5)" || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
