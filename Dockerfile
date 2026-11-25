FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
COPY config ./config
COPY formreview ./formreview
COPY accounts ./accounts
COPY documents ./documents
COPY extraction ./extraction
COPY reviews ./reviews
COPY evaluation ./evaluation
COPY datasets ./datasets
RUN mkdir /app/private && chown 10001:10001 /app/private && chmod 700 /app/private
COPY manage.py ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=2); assert r.status == 200 and json.load(r) == {'status':'ok'}"
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30"]
