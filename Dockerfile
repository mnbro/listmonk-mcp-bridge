FROM ghcr.io/astral-sh/uv:0.9.30 AS uv

FROM python:3.13-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="listmonk-mcp-bridge" \
      org.opencontainers.image.description="MCP server for Listmonk newsletter operations" \
      org.opencontainers.image.source="https://github.com/mnbro/listmonk-mcp-bridge" \
      org.opencontainers.image.licenses="PolyForm-Internal-Use-1.0.0"

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --home-dir /home/mcp --shell /usr/sbin/nologin mcp

COPY --from=builder /app/.venv /app/.venv

USER mcp

ENTRYPOINT ["listmonk-mcp-bridge"]
