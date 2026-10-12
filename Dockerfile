# Urai API+web — self-hosted DeepSeek-style endpoint + playground.
# Build:  docker build -t urai .
# Run:    docker run -p 8777:8777 -e URAI_MODEL=coder05-fast \
#           -e URAI_API_KEY=$(openssl rand -hex 24) \
#           -v urai-model:/app/model -v urai-out:/app/out urai
# Then open http://localhost:8777
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update -qq && apt-get install -y -qq \
    build-essential cmake curl libcurl4-openssl-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Build the llama.cpp runner (pinned commit) at image build time so the
# container starts fast. stable-diffusion.cpp builds on first imagine
# request if missing (or prebuild with: cmake --build ... --target sd-cli).
ARG LLAMA_CPP_COMMIT=7049ff0cbeb1f5ead231de4522af6b75d8d773c0
RUN git init third_party/llama.cpp && cd third_party/llama.cpp \
 && git remote add origin https://github.com/ggml-org/llama.cpp.git \
 && git fetch --depth 1 origin ${LLAMA_CPP_COMMIT} \
 && git checkout FETCH_HEAD \
 && cd /app && cmake -S third_party/llama.cpp -B third_party/llama.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF \
 && cmake --build third_party/llama.cpp/build -j$(nproc) --target llama-cli llama-bench llama-quantize llama-server \
 && rm -rf third_party/llama.cpp/.git \
 && cd /app && python3 -m py_compile jev/*.py scripts/*.py scripts/distill/*.py \
 && chmod +x bin/urai bin/jev docker/entrypoint.sh

EXPOSE 8777
VOLUME ["/app/model", "/app/out", "/app/data"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
