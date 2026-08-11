# Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
uv build
```

## MCP SDK Compatibility

The bridge supports the official MCP Python SDK `>=2.0,<3`. Production code uses
only the SDK's public API, and every direct `mcp` import is confined to
`src/listmonk_mcp/mcp_adapter.py`. Keep bridge policy and tool implementations
independent of SDK model names so a future major-version migration remains
localized to that adapter.

CI checks both MCP 2.0.0 and the newest available v2 release. The protocol suite
exercises negotiated modern mode and explicit legacy mode, cancellation, server
lifespan cleanup, and the installed wheel with Python warnings treated as errors.
When changing the SDK boundary, update the lockfile and keep all of these checks
passing before release.

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

## Listmonk API Compatibility

Run the local, network-free contract gate before publishing changes:

```bash
python scripts/listmonk_api_compat.py validate
```

The scheduled `Listmonk API Watch` workflow polls stable upstream releases. It
derives a contract from Listmonk's Go router and OpenAPI document, opens a draft
PR for changed metadata, and fails closed when routes are new, removed, or no
longer match the bridge. Update `compatibility/listmonk-api-policy.json` only
after implementing a route or documenting why it remains omitted.

Changes to routes, schemas, permissions, or relevant upstream handler source also
change the contract fingerprint. After reviewing and resolving the generated
diff, acknowledge that exact contract before rerunning validation:

```bash
python scripts/listmonk_api_compat.py acknowledge --write
```

Repository variable `LISTMONK_API_ASSIGN_COPILOT=true` optionally assigns a
review-required tracking issue to Copilot. The agent targets the automation
branch; the main compatibility PR still requires normal CI and review.

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
