# Listmonk MCP Bridge

[![PyPI version](https://img.shields.io/pypi/v/listmonk-mcp-bridge.svg)](https://pypi.org/project/listmonk-mcp-bridge/)
[![Python versions](https://img.shields.io/pypi/pyversions/listmonk-mcp-bridge.svg)](https://pypi.org/project/listmonk-mcp-bridge/)
[![License](https://img.shields.io/github/license/mnbro/listmonk-mcp-bridge.svg)](LICENSE)
[![CI](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/ci.yml)
[![Docs](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/docs.yml/badge.svg)](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/docs.yml)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](https://mypy-lang.org/)
[![GitHub release](https://img.shields.io/github/v/release/mnbro/listmonk-mcp-bridge)](https://github.com/mnbro/listmonk-mcp-bridge/releases)
[![Downloads](https://img.shields.io/pypi/dm/listmonk-mcp-bridge.svg)](https://pypistats.org/packages/listmonk-mcp-bridge)

MCP server for [Listmonk](https://listmonk.app/) newsletter operations.

Documentation: https://mnbro.github.io/listmonk-mcp-bridge/

## What it does

`listmonk-mcp-bridge` lets MCP clients work with the Listmonk API through typed tools for subscribers, lists, campaigns, templates, media, analytics, imports, bounces and transactional messages.

It includes runtime confirmations for destructive actions, real email sends and sensitive reads.

## License

This project is licensed under the [PolyForm Internal Use License 1.0.0](LICENSE).

You may use and modify it for your own internal business operations, including commercial internal use. You may not redistribute it, resell it, sublicense it, or offer it as a productized service to third parties.

## Install

Run directly with `uvx`:

```bash
uvx listmonk-mcp-bridge
```

Or install with `pip`:

```bash
pip install listmonk-mcp-bridge
listmonk-mcp-bridge
```

## Configure

Required environment variables:

```bash
export LISTMONK_MCP_URL=https://listmonk.example.com
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-api-token
```

Use a dedicated Listmonk API user and token. Do not use the default admin account in production.

## MCP client config

```json
{
  "mcpServers": {
    "listmonk-mcp-bridge": {
      "command": "uvx",
      "args": ["listmonk-mcp-bridge"],
      "env": {
        "LISTMONK_MCP_URL": "https://listmonk.example.com",
        "LISTMONK_MCP_USERNAME": "api-user",
        "LISTMONK_MCP_PASSWORD": "your-api-token"
      }
    }
  }
}
```

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
```

Full setup, tool behavior, client-specific configuration and security notes are in the documentation site.
