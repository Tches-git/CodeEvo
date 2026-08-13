FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN addgroup --system codeevo && adduser --system --ingroup codeevo --home /app codeevo
COPY --chown=codeevo:codeevo codeevo ./codeevo
COPY --chown=codeevo:codeevo alembic.ini ./alembic.ini
COPY --chown=codeevo:codeevo skills ./skills
USER codeevo
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]
CMD ["python", "-m", "codeevo"]
