FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8100
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
COPY config ./config
COPY evals ./evals
RUN pip install --no-cache-dir . && useradd --create-home saarthi && mkdir -p /srv/data && chown saarthi /srv/data
USER saarthi
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
# The host sets PORT. Proxy headers are trusted so the HTTPS redirect sees the original scheme.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*'"]
