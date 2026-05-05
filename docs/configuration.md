# Configuration

The server is configured through environment variables with the `LISTMONK_MCP_` prefix.

| Variable | Required | Default | Description |
| --- | ---: | --- | --- |
| `LISTMONK_MCP_URL` | yes | none | Base URL of your Listmonk instance. Must start with `http://` or `https://`. |
| `LISTMONK_MCP_USERNAME` | yes | none | Listmonk API username. |
| `LISTMONK_MCP_PASSWORD` | yes | none | Listmonk API token or password. Prefer an API token. |
| `LISTMONK_MCP_MODE` | no | `agentic` | `agentic` exposes the curated LLM-friendly tool surface. `full` exposes every implemented low-level Listmonk wrapper. |
| `LISTMONK_MCP_READ_ONLY` | no | `true` | Blocks real writes, sends, imports, uploads and admin operations before any Listmonk HTTP request. |
| `LISTMONK_MCP_TIMEOUT` | no | `30` | HTTP timeout in seconds. |
| `LISTMONK_MCP_MAX_RETRIES` | no | `3` | HTTP retry attempts for transient failures on safe methods only. Unsafe writes are not blindly retried. |
| `LISTMONK_MCP_DEFAULT_LIMIT` | no | `50` | Default limit for catalog/list-style helper responses. |
| `LISTMONK_MCP_MAX_LIMIT` | no | `500` | Maximum accepted limit for bounded responses. |
| `LISTMONK_MCP_MAX_RESPONSE_BYTES` | no | `1000000` | Response size policy value reported by diagnostics/capabilities. |
| `LISTMONK_MCP_AUDIT_ENABLED` | no | `true` | Enables structured JSONL audit logging. |
| `LISTMONK_MCP_AUDIT_LOG_PATH` | no | `data/audit.jsonl` | Path for standardized audit events. |
| `LISTMONK_MCP_AUDIT_INCLUDE_BLOCKED_ATTEMPTS` | no | `true` | Logs blocked high-risk attempts, including read-only blocks. |
| `LISTMONK_MCP_AUDIT_STRICT` | no | `false` | If true, audit write failures fail high-risk operations. |
| `LISTMONK_MCP_DEBUG` | no | `false` | Enable debug logging. Do not use with sensitive production traffic unless logs are protected. |
| `LISTMONK_MCP_LOG_LEVEL` | no | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LISTMONK_MCP_SERVER_NAME` | no | `Listmonk MCP Bridge` | MCP server display name. |
| `LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE` | no | `30` | Per-process limit for query-driven bulk operations. Use `0` to disable. |

## Authentication

Listmonk token authentication uses this format internally:

```http
Authorization: token username:api_token
```

Use a dedicated API user with the least privileges needed for your MCP workflows.

## Example

```bash
export LISTMONK_MCP_URL=https://listmonk.example.com
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-api-token
export LISTMONK_MCP_MODE=agentic
export LISTMONK_MCP_READ_ONLY=true
export LISTMONK_MCP_LOG_LEVEL=INFO
```

## Enabling Writes

Production defaults are conservative: `LISTMONK_MCP_MODE=agentic` and
`LISTMONK_MCP_READ_ONLY=true`.

To perform a real write, set:

```bash
export LISTMONK_MCP_READ_ONLY=false
```

Then call the relevant safe helper with its explicit confirmation flag, such as
`confirmApply=true`, `confirmSend=true`, `confirmImport=true`,
`confirmUpload=true` or `confirmSchedule=true`. Low-level destructive tools in
full mode still require `confirm=true` or `confirm_send=true` where applicable.

## Capability And Diagnostics

Use `listmonk_capability_report` to inspect the active mode, read-only state,
available tools, hidden full-mode tools, risk class counts, audit settings,
response limits and safe upstream host. Use `listmonk_diagnostics` for a smaller
operational status response. Neither tool returns credentials or raw settings.

## Local `.env`

The runtime can load a `.env` file when running locally. Do not commit real credentials.
