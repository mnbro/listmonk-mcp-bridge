# Listmonk MCP Bridge

[![PyPI version](https://img.shields.io/pypi/v/listmonk-mcp-bridge.svg)](https://pypi.org/project/listmonk-mcp-bridge/)
[![Python versions](https://img.shields.io/pypi/pyversions/listmonk-mcp-bridge.svg)](https://pypi.org/project/listmonk-mcp-bridge/)
[![License](https://img.shields.io/badge/license-PolyForm%20Internal%20Use%201.0.0-blue)](LICENSE)
[![CI](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/ci.yml)
[![Docs](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/docs.yml/badge.svg)](https://github.com/mnbro/listmonk-mcp-bridge/actions/workflows/docs.yml)
[![Container](https://img.shields.io/badge/package-ghcr.io%2Fmnbro%2Flistmonk--mcp--bridge-blue)](https://github.com/mnbro/listmonk-mcp-bridge/pkgs/container/listmonk-mcp-bridge)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](https://mypy-lang.org/)
[![GitHub release](https://img.shields.io/github/v/release/mnbro/listmonk-mcp-bridge)](https://github.com/mnbro/listmonk-mcp-bridge/releases)
[![Downloads](https://img.shields.io/pypi/dm/listmonk-mcp-bridge.svg)](https://pypistats.org/packages/listmonk-mcp-bridge)

MCP server for [Listmonk](https://listmonk.app/) newsletter operations.

Documentation: https://mnbro.github.io/listmonk-mcp-bridge/

- Tool list: https://mnbro.github.io/listmonk-mcp-bridge/tools/
- Docker: https://mnbro.github.io/listmonk-mcp-bridge/docker/
- Configuration: https://mnbro.github.io/listmonk-mcp-bridge/configuration/
- MCP clients: https://mnbro.github.io/listmonk-mcp-bridge/mcp-clients/
- API coverage: https://mnbro.github.io/listmonk-mcp-bridge/api-coverage/
- Safeguards: https://mnbro.github.io/listmonk-mcp-bridge/safeguards/

## What it does

`listmonk-mcp-bridge` lets MCP clients work with the Listmonk API through typed tools for subscribers, lists, campaigns, templates, media, analytics, imports, bounces and transactional messages.

It includes runtime confirmations for destructive actions, real email sends and sensitive reads.

## LLM-friendly helper tools

This MCP remains a generic Listmonk domain MCP. It does not orchestrate external systems, call other MCP servers, or hardcode external workflows.

The helper tools are built on top of the existing Listmonk API wrappers. They give LLM agents safer primitives for subscriber profile sync, audience inspection, personalization validation, campaign risk checks, guarded sends, generic exports and audit logs.

Recommended helper tools for agents:

- `upsert_subscriber_profiles`
- `get_subscriber_context`
- `audience_summary`
- `personalization_fields_report`
- `validate_message_personalization`
- `campaign_risk_check`
- `safe_test_campaign`
- `safe_send_campaign`
- `safe_schedule_campaign`
- `safe_send_transactional_email`
- `campaign_performance_summary`
- `export_engagement_events`
- `export_campaign_markdown`
- `export_campaign_postmortem_markdown`
- `export_subscriber_communication_summary`

## Recommended tools for LLM agents / orchestrators

Recommended:

- `audience_summary`
- `personalization_fields_report`
- `validate_message_personalization`
- `campaign_risk_check`
- `safe_test_campaign`
- `safe_send_campaign`
- `safe_schedule_campaign`
- `safe_send_transactional_email`
- `campaign_performance_summary`
- `export_campaign_markdown`
- `export_campaign_postmortem_markdown`
- `export_engagement_events`
- `get_subscriber_context`
- `upsert_subscriber_profiles` with `dryRun=true` before any non-dry-run execution

Avoid direct use by LLM agents unless explicitly needed:

- `send_campaign`
- `test_campaign`
- `schedule_campaign`
- `send_transactional_email`
- `update_subscriber`
- `delete_campaign`
- `delete_subscribers*`
- `blocklist*`
- `manage_subscriber_lists*`
- `update_settings`
- `reload_app`

Reason: use the `safe_*` wrappers for confirmation, approval checks,
idempotency, risk checks and audit logs. The low-level `schedule_campaign`
tool now requires `confirm_send=true`, but `safe_schedule_campaign` remains the
recommended entry point for agents.

Example profile sync dry run:

```json
{
  "profiles": [
    {
      "externalId": "abc-123",
      "source": "external-system",
      "email": "jane@example.com",
      "name": "Jane Doe",
      "attributes": {
        "birthday": "1990-05-10",
        "customer_type": "vip"
      },
      "tags": ["vip"],
      "listIds": [1, 2],
      "status": "enabled"
    }
  ],
  "dryRun": true
}
```

`upsert_subscriber_profiles` looks up existing subscribers by email before planning or
applying changes. In the current implementation that lookup uses Listmonk's subscriber
SQL query capability, so the MCP API key needs the `subscribers:sql_query` permission.
Without it, dry runs and upserts can return a Listmonk permission error.

Example personalization and send checks:

```json
{
  "email": "jane@example.com"
}
```

```json
{
  "listIds": [1, 2],
  "filters": {}
}
```

```json
{
  "subject": "Hello {{name}}",
  "body": "We have an update for {{customer_type}} subscribers.",
  "listIds": [1],
  "sampleSubscriberIds": [123, 456]
}
```

```json
{
  "campaignId": 123,
  "requireTestSend": true,
  "maxAudienceSize": 5000
}
```

```json
{
  "campaignId": 123,
  "testRecipients": ["test@example.com"],
  "confirmSend": true
}
```

```json
{
  "campaignId": 123,
  "confirmSend": true,
  "approval": {
    "required": true,
    "status": "approved",
    "approvalId": "approval-123"
  },
  "requireTestSend": true,
  "testRecipients": ["test@example.com"]
}
```

```json
{
  "templateId": 10,
  "recipientEmail": "jane@example.com",
  "subject": "A message for Jane",
  "data": {
    "name": "Jane",
    "customMessage": "Happy birthday"
  },
  "contentType": "html",
  "confirmSend": true,
  "idempotencyKey": "unique-event-key-123"
}
```

Example generic exports:

```json
{
  "campaignId": 123,
  "fromDate": "2026-04-01",
  "toDate": "2026-04-30"
}
```

```json
{
  "campaignId": 123,
  "eventTypes": ["email_viewed", "email_clicked"]
}
```

```json
{
  "campaignId": 123,
  "includeBody": true,
  "includeStats": true
}
```

```json
{
  "subscriberId": 123,
  "fromDate": "2026-01-01",
  "toDate": "2026-04-30"
}
```

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

## Docker

The Debian slim based container image is published to GitHub Container Registry:

```bash
docker run --rm -i \
  --env LISTMONK_MCP_URL=https://listmonk.example.com \
  --env LISTMONK_MCP_USERNAME \
  --env LISTMONK_MCP_PASSWORD \
  ghcr.io/mnbro/listmonk-mcp-bridge:latest
```

See the [Docker documentation](https://mnbro.github.io/listmonk-mcp-bridge/docker/) for MCP client configuration.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
```

Full setup, tool behavior, API coverage, client-specific configuration and security notes are in the documentation site.
