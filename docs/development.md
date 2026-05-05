# Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
uv build
```

## MCP Inspector Validation

Use MCP Inspector before release or when changing tool registration:

1. Start the server with defaults: `LISTMONK_MCP_MODE=agentic` and
   `LISTMONK_MCP_READ_ONLY=true`.
2. Open MCP Inspector against the stdio command used by your client.
3. Verify that only agentic tools are visible.
4. Verify safe resources are visible, including `listmonk://health`,
   `listmonk://capabilities`, `listmonk://lists`,
   `listmonk://campaigns/summary` and `listmonk://templates/summary`.
5. Verify prompts are visible: `inspect_listmonk_audience`,
   `create_campaign_safely`, `send_campaign_safely`,
   `import_subscribers_safely`, `review_campaign_performance` and
   `debug_listmonk_connection`.
6. Call `check_listmonk_health`, `listmonk_diagnostics` and
   `listmonk_capability_report`.
7. Attempt dry-run safe create/update/import/send workflows.
8. Attempt a real write while read-only is enabled and verify it is blocked
   before an upstream HTTP request.
9. Restart with `LISTMONK_MCP_MODE=full` and verify the low-level Listmonk API
   wrappers are visible.

## Versioning And Deprecation

The project follows semantic versioning. Tool names and input schemas are public
API. Breaking tool schema changes require a major version bump. Deprecated tools
remain available for at least one minor release and should return
`deprecated=true` with a clear `deprecationMessage` where practical.

Release notes are maintained in `CHANGELOG.md`. Documentation is versioned in
`docs/` and published to GitHub Pages through the docs workflow.

## Transport Strategy

The supported production transport is stdio. Docker usage should still expose
the MCP server through stdio. Do not expose a public HTTP transport unless TLS,
authentication, rate limits and request size limits are implemented.

## Docker Build

```bash
docker build -t listmonk-mcp-bridge:local .
```

## Staging Smoke Tests

Staging smoke tests are opt-in and should only run against a disposable or staging Listmonk instance. They exercise settings update, import and email send paths.

## Documentation

Documentation is versioned in `docs/` and published to GitHub Pages through the docs workflow.

## Acknowledgements

Earlier project history referenced `rhnvrm/listmonk-mcp`. The current implementation was rewritten around the public Listmonk API surface and this project's own safety and operational requirements.
