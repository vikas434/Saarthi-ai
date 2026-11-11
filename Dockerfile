FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
COPY config ./config
COPY evals ./evals
RUN pip install --no-cache-dir -e . && useradd --create-home sqs && mkdir -p /srv/data && chown sqs /srv/data
USER sqs
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
