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

Connect [Listmonk](https://listmonk.app/) to AI agents so they can safely manage email lists, subscribers, campaigns, test sends, transactional emails, and performance reports.

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

## Recommended tools for LLM agents / orchestrators

This MCP remains a generic Listmonk domain MCP. It does not orchestrate external systems, call other MCP servers, or hardcode external workflows. For full tool behavior and schemas, use the [tool documentation](https://mnbro.github.io/listmonk-mcp-bridge/tools/) and [safeguards documentation](https://mnbro.github.io/listmonk-mcp-bridge/safeguards/).

Recommended for autonomous LLM/orchestrator use:

- `check_listmonk_health`
- `get_mailing_lists`
- `get_list_subscribers_tool`
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
- `export_campaign_markdown`
- `export_campaign_postmortem_markdown`
- `export_engagement_events`
- `export_subscriber_communication_summary`
- `upsert_subscriber_profiles` with `dryRun=true` before any non-dry-run execution

These tools are LLM-friendly because they return compact summaries, warnings and blockers; use guardrails for confirmations, risk checks, approvals and idempotency where relevant; avoid accidental sends; and are suitable building blocks for external business orchestrators.

Supervised / low-level only:

- `send_campaign`
- `test_campaign`
- `schedule_campaign`
- `send_transactional_email`
- `add_subscriber`
- `update_subscriber`
- `change_subscriber_status`
- `manage_subscriber_lists`
- `manage_subscriber_lists_by_query`
- `delete_subscribers_by_query`
- `blocklist_subscriber`
- `blocklist_subscribers`
- `blocklist_subscribers_by_query`
- `remove_subscriber`
- `remove_subscribers`
- `create_campaign`
- `update_campaign`
- `update_campaign_status`
- `archive_campaign`
- `convert_campaign_content`
- `replace_in_campaign_body`
- `regex_replace_in_campaign_body`
- `batch_replace_in_campaign_body`
- `create_template`
- `update_template`
- `delete_template`
- `set_default_template`
- `create_mailing_list`
- `update_mailing_list`
- `delete_mailing_list`
- `delete_mailing_lists`
- `import_subscribers`
- `upload_media_file`
- `rename_media`
- `delete_media_file`
- `update_settings`
- `reload_app`

Some low-level tools have confirmation guards, but they are still closer to the raw Listmonk API. Prefer `safe_*` wrappers for LLM workflows. For content changes, preview and risk-check before mutating operations.

## Recommended workflows

Campaign flow: `check_listmonk_health` -> `audience_summary` -> `personalization_fields_report` -> `validate_message_personalization` -> `campaign_risk_check` -> `get_campaign_html_preview` or `export_campaign_markdown` -> `safe_test_campaign` -> external approval if required -> `safe_schedule_campaign` or `safe_send_campaign` -> `campaign_performance_summary` -> `export_campaign_postmortem_markdown`.

Do not use `send_campaign` directly in an orchestrator. Do not use `schedule_campaign` directly unless there is an explicit low-level reason. Prefer `safe_test_campaign` before `safe_send_campaign`; when `safe_send_campaign` uses `requireTestSend=true`, provide `testRecipients`.

Transactional email flow: `get_subscriber_context` -> `validate_message_personalization` if subject/body are generated -> `safe_send_transactional_email` with `confirmSend=false` for a safety check -> `safe_send_transactional_email` with `confirmSend=true` only after an explicit decision. Use an `idempotencyKey` for recurring events, for example `birthday-email:{subscriberId}:{year}`.

Transactional `data` accepts `object | null` and may contain nested JSON. Some connector renderers show only example fields such as `name` and `customMessage`, but the schema keeps `additionalProperties=true`, so arbitrary template variables are allowed.

Subscriber sync flow: `get_subscriber_context` by email -> `upsert_subscriber_profiles` with `dryRun=true` -> inspect `plannedCreated`, `plannedUpdated` and `errors` -> run `upsert_subscriber_profiles` with `dryRun=false` only after external confirmation.

`upsert_subscriber_profiles` looks up subscribers by email. It needs the relevant Listmonk subscriber permissions, including `subscribers:sql_query` if SQL lookup is used. Email literals are quoted safely, including apostrophes. In production, use `dryRun=true` before any write.

## Production safety model

- Sensitive read tools require `confirm_read`.
- Send tools require `confirm_send`.
- Destructive tools require `confirm`.
- Scheduling tools require `confirm_send` or `confirmSchedule`.
- `safe_*` wrappers are preferred for LLM agents.
- Approval metadata can block send/schedule even when confirmation is true.
- `idempotencyKey` prevents duplicate transactional email sends.
- Safe confirmed operations return an `auditId`.

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
