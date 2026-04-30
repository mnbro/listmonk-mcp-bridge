# Listmonk MCP Bridge

`listmonk-mcp-bridge` is a Model Context Protocol server for Listmonk newsletter operations. It gives MCP clients typed access to subscribers, lists, campaigns, templates, media, analytics, imports, bounces, transactional email and operational admin endpoints.

Repository: https://github.com/mnbro/listmonk-mcp-bridge

PyPI: https://pypi.org/project/listmonk-mcp-bridge/

Container image: `ghcr.io/mnbro/listmonk-mcp-bridge:latest`

## Quick Links

- [Tool list](tools.md)
- [Docker](docker.md)
- [Configuration](configuration.md)
- [MCP clients](mcp-clients.md)
- [API coverage](api-coverage.md)
- [Safeguards](safeguards.md)
- [Development](development.md)

## What It Does

The bridge connects MCP clients to the Listmonk REST API through typed tools instead of ad-hoc HTTP calls.

Typical workflows:

- Search, create and update subscribers.
- Manage mailing lists and public subscription flows.
- Create, preview, schedule, send and inspect campaigns.
- Work with templates, media and transactional email.
- Read dashboard metrics, campaign analytics, bounces and import status.
- Run guarded operational actions with explicit confirmations.

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

## Minimal Configuration

```bash
export LISTMONK_MCP_URL=https://listmonk.example.com
export LISTMONK_MCP_USERNAME=api-user
export LISTMONK_MCP_PASSWORD=your-api-token
```

Use a dedicated Listmonk API user and token. Avoid using the default admin account in production.

## MCP Client Config

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

## Runtime Safety

The server uses MCP `ToolAnnotations` and runtime confirmations for sensitive reads, destructive actions and real email sends. See [Safeguards](safeguards.md) for the confirmation model and logging behavior.

## License

This project is licensed under the [PolyForm Internal Use License 1.0.0](https://polyformproject.org/licenses/internal-use/1.0.0).
