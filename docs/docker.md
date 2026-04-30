# Docker

The project publishes a Debian slim based MCP server image to GitHub Container Registry:

```text
ghcr.io/mnbro/listmonk-mcp-bridge:latest
```

The image runs as a non-root user and starts the MCP server over stdio. It does not contain credentials or a Listmonk instance.

## Run

Pass credentials as environment variables. Prefer inheriting secrets from the host or your secret manager instead of writing secret values directly into shell history.

```bash
docker run --rm -i \
  --env LISTMONK_MCP_URL=https://listmonk.example.com \
  --env LISTMONK_MCP_USERNAME \
  --env LISTMONK_MCP_PASSWORD \
  ghcr.io/mnbro/listmonk-mcp-bridge:latest
```

## MCP Client Config

```json
{
  "mcpServers": {
    "listmonk-mcp-bridge": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--env",
        "LISTMONK_MCP_URL=https://listmonk.example.com",
        "--env",
        "LISTMONK_MCP_USERNAME",
        "--env",
        "LISTMONK_MCP_PASSWORD",
        "ghcr.io/mnbro/listmonk-mcp-bridge:latest"
      ]
    }
  }
}
```

## Build Locally

```bash
docker build -t listmonk-mcp-bridge:local .
```

Use `:latest` for the current master build, `:vX.Y.Z` for a release, or `:sha-...` for an immutable commit build.

## Running Listmonk

This image contains only the MCP server. If you need a local Listmonk instance for development, see [Listmonk Docker Setup](docker-setup.md).
