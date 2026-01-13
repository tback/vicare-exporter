FROM python:3.13-alpine

ENV UV_NO_DEV=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY uv.lock . 
COPY pyproject.toml .

RUN uv sync --frozen 

COPY vicare_exporter ./vicare_exporter

CMD [ "uv", "run", "python", "-m", "vicare_exporter" ]
