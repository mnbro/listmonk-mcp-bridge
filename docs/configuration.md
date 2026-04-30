# Configuration

The server is configured through environment variables with the `LISTMONK_MCP_` prefix.

| Variable | Required | Default | Description |
| --- | ---: | --- | --- |
| `LISTMONK_MCP_URL` | yes | none | Base URL of your Listmonk instance. Must start with `http://` or `https://`. |
| `LISTMONK_MCP_USERNAME` | yes | none | Listmonk API username. |
| `LISTMONK_MCP_PASSWORD` | yes | none | Listmonk API token or password. Prefer an API token. |
| `LISTMONK_MCP_TIMEOUT` | no | `30` | HTTP timeout in seconds. |
| `LISTMONK_MCP_MAX_RETRIES` | no | `3` | HTTP retry attempts for transient failures. |
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
export LISTMONK_MCP_LOG_LEVEL=INFO
```

## Local `.env`

The runtime can load a `.env` file when running locally. Do not commit real credentials.
