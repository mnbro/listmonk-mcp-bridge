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

Use `:latest` for the current master build or `:vX.Y.Z` for a release.
The `:sha-...` tags identify the source commit; pin an image digest (`@sha256:...`)
when you need immutable image contents.

## Automatic Security Rebuilds

The existing Container workflow rebuilds `:latest` and `:master` every day at
05:43 UTC, as well as after code changes. Each build pulls the current
`python:3.13-slim-bookworm` image and refreshes Debian packages in an uncached
base stage shared by the builder and runtime. This picks up published Debian
fixes even before the Python image maintainers rebuild their image.

The build checks the installed command as the non-root runtime user before
publishing. Scheduled and manual rebuilds also get a
`:rebuild-<run-id>-<attempt>` tag; they do not overwrite existing release or
commit tags. GitHub schedules can be delayed, so use **Run workflow** on
Container when an urgent rebuild is needed.

Pull the refreshed image and recreate your container to apply the fixes to an
existing installation. Running containers do not update themselves.

## Running Listmonk

This image contains only the MCP server. If you need a local Listmonk instance for development, see [Listmonk Docker Setup](docker-setup.md).
