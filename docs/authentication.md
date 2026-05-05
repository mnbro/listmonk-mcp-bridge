# Authentication

Use a dedicated Listmonk API user for this MCP server. Prefer an API token over
an account password and grant only the permissions needed by the workflows you
intend to expose.

The bridge sends Listmonk authentication as:

```http
Authorization: token username:api_token
```

Do not place credentials in prompts, tool arguments, audit summaries or source
control. Configure them through environment variables or your deployment secret
manager:

```bash
export LISTMONK_MCP_URL=https://listmonk.example.com
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=api-token
```

Production deployments should keep `LISTMONK_MCP_MODE=agentic` and
`LISTMONK_MCP_READ_ONLY=true` by default. Enable writes only for supervised
sessions, and only with the relevant confirmation flags.
