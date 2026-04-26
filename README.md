# Listmonk MCP Bridge

A production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for [Listmonk](https://listmonk.app/), built to give AI assistants and automation agents structured access to newsletter, subscriber, mailing list, campaign, template, and reporting workflows.


## Origin and fork notice

This repository began as an initial fork of [`rhnvrm/listmonk-mcp`](https://github.com/rhnvrm/listmonk-mcp).

It has since evolved into `listmonk-mcp-bridge`: a production-ready MCP server for Listmonk with updated packaging, CLI entry points, environment-based configuration, validation, development tooling, and operational documentation suitable for real deployments.

## Overview

`listmonk-mcp-bridge` bridges MCP clients with the Listmonk REST API. It enables LLMs, AI assistants, and automation workflows to interact with Listmonk through a typed and predictable interface instead of ad-hoc HTTP calls.

Typical use cases include:

- Subscriber lookup, creation, updates, and lifecycle management
- Mailing list discovery and management
- Campaign creation, updates, and delivery workflows
- Template and content operations
- Analytics and reporting access
- Agent-driven newsletter and communications automation

## What changed for production readiness

Compared with the initial fork baseline, this package has been substantially updated, packaged, and hardened for production use under the `listmonk-mcp-bridge` package name.

Production-focused improvements include:

- PyPI-ready packaging with `uv`, `uvx`, `pip`, and console entry points
- Environment-based configuration suitable for local, staging, and production deployments
- Async HTTP operations for reliable Listmonk API communication
- Pydantic-based validation for safer input and output handling
- CLI entry points via both `listmonk-mcp-bridge` and `listmonk-mcp`
- Development tooling with Ruff, mypy, pytest, and build validation
- Release workflow support for publishing to PyPI and GitHub releases
- Clear operational notes for credentials, API tokens, and production safety

## Features

- **Broad Listmonk API coverage** for subscriber, list, campaign, and template workflows
- **81 MCP tools** covering all 72 Listmonk Swagger operations plus focused convenience workflows
- **MCP resources** for structured access to Listmonk data
- **Async-first implementation** built on modern Python patterns
- **Type-safe models** using Pydantic validation
- **Environment-driven configuration** for local, staging, and production environments
- **MCP tool annotations** for read-only, side-effecting, email-sending, and destructive operations
- **Runtime confirmations** for destructive operations, real email sends, and sensitive reads
- **Structured audit logs** for confirmed high-impact operations with PII/query redaction
- **Per-process bulk query rate limiting** for query-driven destructive operations
- **Opt-in staging smoke tests** for settings updates, imports, and email send paths
- **Developer tooling** with Ruff, mypy, pytest, Black, and build checks

## Tool behavior notes

- `update_subscriber` uses Listmonk's `PATCH /api/subscribers/{id}` endpoint for partial updates. Omitted fields are not sent to Listmonk, so changing only `name`, `status`, `lists`, or `attributes` does not require an `email`.
- Sensitive subscriber updates require `confirm=true` when blocklisting or replacing list memberships.
- `create_template` supports campaign, `campaign_visual`, and transactional (`tx`) templates, including `subject` and `body_source`.
- `create_campaign` converts `content_type="plain"` bodies into escaped HTML paragraphs by default with `auto_convert_plain_to_html=True`. Set `auto_convert_plain_to_html=False` to send plain text unchanged. HTML bodies are always left unchanged.
- Swagger-aligned tools cover public lists, subscriber opt-in/export/bounces/list membership, bounces, import status/logs/stop, campaign delete/status/stats/analytics/archive/test/content conversion, template preview/default, media lookup, and extended transactional messages.

## Operational safeguards

The server exposes MCP `ToolAnnotations` and runtime guardrails so MCP clients can reason about operational risk and so accidental high-impact calls fail closed.

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

## Requirements

- Python 3.11 or newer
- A running Listmonk instance
- A Listmonk API user and API token
- One of the following package runners or installers:
  - `uv` / `uvx` recommended
  - `pip`

## Installation

### Run with `uvx` recommended

Run the server directly from PyPI without manually managing a virtual environment:

```bash
uvx listmonk-mcp-bridge --help
```

Install it as a globally available tool:

```bash
uvx install listmonk-mcp-bridge
listmonk-mcp-bridge --help
```

### Install with `pip`

```bash
pip install listmonk-mcp-bridge
```

After installation, the following commands are available:

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

Example local configuration:

```bash
export LISTMONK_MCP_URL=http://localhost:9000
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-generated-api-token
```

Listmonk token authentication uses the following format internally:

```http
Authorization: token username:api_token
```

## Quick start

### 1. Start Listmonk locally

For local development and testing, you can run Listmonk with Docker.

Using the compose file included in this repository:

```bash
docker compose -f docs/listmonk-docker-compose.yml up -d
```

Or using the official Listmonk compose file:

```bash
curl -LO https://github.com/knadh/listmonk/raw/master/docker-compose.yml
docker compose up -d
```

Listmonk should be available at:

```text
http://localhost:9000
```

Default local credentials are typically:

```text
admin / listmonk
```

### 2. Create a dedicated Listmonk API user

1. Open the Listmonk admin interface.
2. Navigate to **Admin → Users**.
3. Create a dedicated API user, for example `api-user`.
4. Assign only the permissions required by your MCP workflows.
5. Generate an API token for that user.
6. Use that token as `LISTMONK_MCP_PASSWORD`.

For production deployments, avoid using the default admin account. Create a dedicated API user with the minimum permissions required.

### 3. Export environment variables

```bash
export LISTMONK_MCP_URL=http://localhost:9000
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-generated-api-token
```

### 4. Run the MCP server

With the installed console command:

```bash
listmonk-mcp-bridge
```

Or through `uv` during development:

```bash
uv run listmonk-mcp-bridge
```

You can also run the Python module directly:

```bash
uv run python -m listmonk_mcp.server
```

## MCP client configuration

Most MCP clients can start this server as a local command. A typical configuration looks like this:

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

If you installed the package globally, you can also use:

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

## Production notes

Before using this server in production, review the following recommendations:

- Use HTTPS for your Listmonk instance.
- Use a dedicated API user instead of an admin user.
- Apply least-privilege permissions wherever possible.
- Store credentials in your deployment secret manager, not in source control.
- Rotate API tokens periodically.
- Test campaign-related workflows against a staging Listmonk instance first.
- Monitor Listmonk API logs for unexpected agent behavior.
- Review any AI-generated campaign or subscriber changes before enabling fully automated flows.
- Ship `listmonk_mcp.audit` and `listmonk_mcp.operations` logs to your normal log pipeline.
- Keep `LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE` enabled unless your deployment has stronger upstream controls.

### Staging smoke tests

Smoke tests that touch a real Listmonk instance are skipped by default. To run them against staging, set:

```bash
export LISTMONK_MCP_RUN_STAGING_SMOKE=true
export LISTMONK_MCP_URL=https://listmonk-staging.example.com
export LISTMONK_MCP_USERNAME=your-api-user
export LISTMONK_MCP_PASSWORD=your-api-token
export LISTMONK_MCP_SMOKE_LIST_ID=1
export LISTMONK_MCP_SMOKE_CAMPAIGN_ID=1
export LISTMONK_MCP_SMOKE_EMAIL=qa@example.com
uv run pytest tests/test_staging_smoke.py -q
```

## Troubleshooting

### Verify environment variables

```bash
echo "$LISTMONK_MCP_URL"
echo "$LISTMONK_MCP_USERNAME"
```

Avoid printing API tokens in shared terminals, CI logs, or screenshots.

### Test Listmonk API access

```bash
curl \
  -H "Authorization: token ${LISTMONK_MCP_USERNAME}:${LISTMONK_MCP_PASSWORD}" \
  "${LISTMONK_MCP_URL}/api/health"
```

### Common issues

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `Connection refused` | Listmonk is not running or the URL is wrong | Check `LISTMONK_MCP_URL` and Listmonk availability |
| `403` or `invalid session` | Invalid username/token or insufficient permissions | Regenerate the API token and verify the API user permissions |
| `Module not found` | Development dependencies are not installed | Run `uv sync --extra dev` |
| CLI command not found | Package not installed in the active environment | Use `uvx listmonk-mcp-bridge` or reinstall the package |

## Development

Clone the repository and install development dependencies:

```bash
git clone https://github.com/mnbro/listmonk-mcp-bridge.git
cd listmonk-mcp-bridge
uv sync --extra dev
```

Run the development server:

```bash
uv run listmonk-mcp-bridge --help
uv run listmonk-mcp-bridge --version
```

### Code quality

Run linting:

```bash
uv run ruff check src/
```

Automatically fix lint issues where possible:

```bash
uv run ruff check src/ --fix
```

Run type checking:

```bash
uv run mypy src/
```

Run tests:

```bash
uv run pytest
```

The default test suite includes guardrail, annotation, schema, audit-redaction, and rate-limit coverage. Staging smoke tests are present but skipped unless explicitly enabled.

Run the main quality checks together:

```bash
uv run ruff check src/ && uv run mypy src/ && uv run pytest
```

### Build locally

```bash
uv build
```

Validate the built distribution before publishing:

```bash
uvx twine check dist/*
```

## Release process

To release a new version:

```bash
# 1. Update the version in pyproject.toml
# Example: 0.2.0 -> 0.2.1

# 2. Commit the version bump
git add pyproject.toml
git commit -m "chore: bump version to 0.2.1"

# 3. Tag the release
git tag v0.2.1

# 4. Push the branch and tag
git push origin master
git push origin v0.2.1
```

If GitHub Actions is configured, the release pipeline can run checks, build the package, publish to PyPI, and create a GitHub release.

## Security

This package can perform real operations against your Listmonk instance, including subscriber and campaign changes. Treat access to the MCP server as privileged access.

Recommended safeguards:

- Run the server only in trusted environments.
- Keep API credentials out of repository files and logs.
- Limit token permissions according to the workflows you actually need.
- Prefer staging environments when testing new automations or agent behavior.
- Review generated campaign content before sending to real audiences.
- Require operators and agents to pass `confirm=true`, `confirm_send=true`, or `confirm_read=true` only after reviewing the requested operation.
- Forward audit and operations logs to centralized logging and alert on unexpected confirmed operations.
- Treat MCP client access as equivalent to privileged Listmonk API access.

## Attribution

This project was initially forked from [`rhnvrm/listmonk-mcp`](https://github.com/rhnvrm/listmonk-mcp). The current `listmonk-mcp-bridge` package has been modified and extended for production-oriented packaging, configuration, validation, and operational use.

Listmonk is an independent open-source project. This package is not officially affiliated with or endorsed by the Listmonk maintainers.

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for details.
