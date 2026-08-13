# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm AS builder

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=8 \
    PIP_INDEX_URL=${PIP_INDEX_URL}
WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY codeevo ./codeevo
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.11-slim-bookworm AS runtime

ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="CodeEvo" \
      org.opencontainers.image.description="Evaluation-gated multi-agent code review platform" \
      org.opencontainers.image.source="https://github.com/Tches-git/CodeEvo" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="0.9.0" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CODEEVO_HOST=0.0.0.0 \
    CODEEVO_PORT=8080 \
    CODEEVO_SKILLS_DIR=/app/skills

RUN addgroup --system codeevo \
    && adduser --system --ingroup codeevo --home /app codeevo \
    && mkdir -p /app/skills /data \
    && chown -R codeevo:codeevo /app /data

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl && rm -rf /wheels
COPY --chown=codeevo:codeevo skills /app/skills

WORKDIR /app
USER codeevo
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3).read()"]

CMD ["python", "-m", "codeevo"]
