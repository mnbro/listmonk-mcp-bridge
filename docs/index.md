# Listmonk MCP Bridge

`listmonk-mcp-bridge` is a Model Context Protocol server for Listmonk. It gives AI assistants and automation agents structured access to newsletter, subscriber, list, campaign, template, media, analytics, import, bounce and transactional email workflows.

Repository: https://github.com/mnbro/listmonk-mcp-bridge

PyPI: https://pypi.org/project/listmonk-mcp-bridge/

## Overview

The bridge connects MCP clients to the Listmonk REST API through typed tools instead of ad-hoc HTTP calls.

Typical use cases include:

- Subscriber lookup, creation, updates and lifecycle management.
- Mailing list discovery and management.
- Campaign creation, updates, test sends and delivery workflows.
- Template and content operations.
- Analytics and reporting access.
- Agent-driven newsletter and communications automation.

## Features

- Broad Listmonk API coverage for subscriber, list, campaign, template and media workflows.
- 81 MCP tools covering all 72 Listmonk Swagger operations plus focused convenience workflows.
- MCP resources for structured access to Listmonk data.
- Async HTTP operations for reliable Listmonk API communication.
- Pydantic validation for safer input and output handling.
- Environment-driven configuration for local, staging and production deployments.
- CLI entry points via `listmonk-mcp-bridge` and `listmonk-mcp`.
- MCP tool annotations for read-only, side-effecting, email-sending and destructive operations.
- Runtime confirmations for destructive operations, real email sends and sensitive reads.
- Structured audit logs for confirmed high-impact operations with PII/query redaction.
- Per-process bulk query rate limiting for query-driven destructive operations.
- Opt-in staging smoke tests for settings updates, imports and email send paths.

## Installation

Run directly with `uvx`:

```bash
uvx listmonk-mcp-bridge
```

Install as a tool:

```bash
uvx install listmonk-mcp-bridge
listmonk-mcp-bridge --help
```

Install with `pip`:

```bash
pip install listmonk-mcp-bridge
```

After installation, these commands are available:

```bash
listmonk-mcp-bridge --help
listmonk-mcp --help
```

## Configuration

The server is configured through environment variables.

| Variable | Required | Description | Example |
| --- | --- | --- | --- |
| `LISTMONK_MCP_URL` | Yes | Base URL of your Listmonk instance | `https://listmonk.example.com` |
| `LISTMONK_MCP_USERNAME` | Yes | Listmonk API username | `api-user` |
| `LISTMONK_MCP_PASSWORD` | Yes | Listmonk API token, not the account login password | `your-api-token` |
| `LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE` | No | Per-process limit for query-driven bulk operations. Use `0` to disable. | `30` |

Listmonk token authentication uses this format internally:

```http
Authorization: token username:api_token
```

## Quick Start

For local testing, start Listmonk with the included Docker Compose file:

```bash
docker compose -f docs/listmonk-docker-compose.yml up -d
```

Listmonk should be available at:

```text
http://localhost:9000
```

Default local credentials are typically:

```text
admin / listmonk
```

Create a dedicated Listmonk API user:

1. Open the Listmonk admin interface.
2. Navigate to **Admin -> Users**.
3. Create a dedicated API user, for example `api-user`.
4. Assign only the permissions required by your MCP workflows.
5. Generate an API token for that user.
6. Use that token as `LISTMONK_MCP_PASSWORD`.

Export environment variables:

```bash
export LISTMONK_MCP_URL=http://localhost:9000
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-generated-api-token
```

Run the MCP server:

```bash
listmonk-mcp-bridge
```

During development:

```bash
uv run listmonk-mcp-bridge
```

## MCP Client Configuration

Most MCP clients can start this server as a local command:

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

If installed globally:

```json
{
  "mcpServers": {
    "listmonk-mcp-bridge": {
      "command": "listmonk-mcp-bridge",
      "env": {
        "LISTMONK_MCP_URL": "https://listmonk.example.com",
        "LISTMONK_MCP_USERNAME": "api-user",
        "LISTMONK_MCP_PASSWORD": "your-api-token"
      }
    }
  }
}
```

Client-specific setup:

- [Claude Desktop](claude-desktop.md)
- [VS Code](vscode.md)
- [Cline](cline.md)
- [Windsurf & Cursor](windsurf-cursor.md)

## Tool Behavior

- `update_subscriber` uses Listmonk's `PATCH /api/subscribers/{id}` endpoint for partial updates. Omitted fields are not sent to Listmonk, so changing only `name`, `status`, `lists`, or `attributes` does not require an `email`.
- Sensitive subscriber updates require `confirm=true` when blocklisting or replacing list memberships.
- `create_template` supports campaign, `campaign_visual` and transactional (`tx`) templates, including `subject` and `body_source`.
- `create_campaign` converts `content_type="plain"` bodies into escaped HTML paragraphs by default with `auto_convert_plain_to_html=True`. Set `auto_convert_plain_to_html=False` to send plain text unchanged. HTML bodies are left unchanged.
- Swagger-aligned tools cover public lists, subscriber opt-in/export/bounces/list membership, bounces, import status/logs/stop, campaign delete/status/stats/analytics/archive/test/content conversion, template preview/default, media lookup and extended transactional messages.

## Operational Safeguards

The server exposes MCP `ToolAnnotations` and runtime guardrails so MCP clients can reason about operational risk and accidental high-impact calls fail closed.

| Operation class | MCP annotation | Runtime requirement |
| --- | --- | --- |
| Strictly read-only tools | `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` | No confirmation, unless the read exposes sensitive data |
| Sensitive reads: `get_settings`, `get_server_config`, `get_logs`, `get_subscriber_export` | `readOnlyHint=true` | `confirm_read=true` |
| Destructive or destructive-like operations: `delete_*`, `remove_*`, `blocklist_*`, GC cleanup, analytics cleanup, stopping imports | `destructiveHint=true` | `confirm=true` |
| Sensitive subscriber/list changes: list removal, unsubscribe, query-based membership changes, blocklist status changes, list replacement | `destructiveHint=true` | `confirm=true` when the risky action is requested |
| Real email sends: `send_campaign`, `send_transactional_email`, `test_campaign`, `send_subscriber_optin` | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=false` | `confirm_send=true` |
| Other side-effecting writes: create/update/import/archive/preview conversion/reload | `readOnlyHint=false`, `idempotentHint=false` | Confirmation where operationally sensitive, such as settings updates and app reloads |

Confirmed high-impact operations emit structured audit log events on the `listmonk_mcp.audit` logger. Audit context redacts email addresses and secret-like fields, and SQL-like query strings are represented by SHA-256 hashes instead of raw query text.

Query-driven bulk operations are rate limited per server process. Configure the limit with `LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE`; the default is `30`, and `0` disables the limit. Allowed and rate-limited events are logged on `listmonk_mcp.operations`.

## Production Notes

- Use HTTPS for your Listmonk instance.
- Use a dedicated API user instead of an admin user.
- Apply least-privilege permissions wherever possible.
- Store credentials in your deployment secret manager, not in source control.
- Rotate API tokens periodically.
- Test campaign-related workflows against a staging Listmonk instance first.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
uv build
```

## Attribution

This repository began as an initial fork of [`rhnvrm/listmonk-mcp`](https://github.com/rhnvrm/listmonk-mcp).

It has since evolved into `listmonk-mcp-bridge`, a packaged and operationally documented MCP server for Listmonk.
