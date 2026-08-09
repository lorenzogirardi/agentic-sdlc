FROM python:3.12-slim

RUN useradd --create-home --shell /bin/bash agent && \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

RUN chown -R agent:agent /app
USER agent

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "orchestrator.engine"]