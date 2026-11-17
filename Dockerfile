FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg espeak-ng fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
RUN useradd -m -u 10001 runner && mkdir -p /data /outputs && chown runner:runner /data /outputs
USER runner
ENTRYPOINT ["news-video"]
CMD ["--help"]
