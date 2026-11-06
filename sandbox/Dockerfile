FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-fastapi \
    uvicorn \
    xvfb \
    x11vnc \
    websockify \
    supervisor \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install google-chrome-stable
RUN wget -q -O /tmp/google-chrome.deb \
    https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update \
    && apt-get install -y /tmp/google-chrome.deb \
    && rm /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Install FastAPI and uvicorn via pip (in case system packages are not up to date)
RUN pip3 install --no-cache-dir fastapi uvicorn python-multipart

WORKDIR /app

COPY api/ /app/

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8080 9222 5900 5901

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
