FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8088

WORKDIR /app
ARG PIP_INDEX_URL
COPY pyproject.toml ./
COPY src/contracts ./src/contracts
COPY src/agents/documentation-agent/app ./src/agents/documentation-agent/app
RUN if [ -n "${PIP_INDEX_URL}" ]; then \
        PIP_INDEX_URL="${PIP_INDEX_URL}" python -m pip install --no-cache-dir ".[agent]"; \
    else \
        python -m pip install --no-cache-dir ".[agent]"; \
    fi \
    && useradd --create-home --uid 10001 agent

USER agent
EXPOSE 8088
CMD ["documentation-agent"]
