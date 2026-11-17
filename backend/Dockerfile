FROM python:3.13-slim AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

WORKDIR /app
RUN pip install --no-cache-dir poetry==2.4.1
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-ansi

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
RUN groupadd --gid 10001 fincore \
    && useradd --uid 10001 --gid fincore --home-dir /app --no-create-home --shell /usr/sbin/nologin fincore
COPY --from=dependencies /app/.venv /app/.venv
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "backend.bootstrap.api"]
