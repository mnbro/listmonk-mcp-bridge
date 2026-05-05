# Listmonk API Surface

This MCP server exposes typed wrappers around the Listmonk REST API instead of a
raw arbitrary request tool. Full mode preserves broad low-level coverage for
subscribers, lists, imports, campaigns, templates, media, bounces, settings,
logs and maintenance/admin actions.

Agentic mode exposes safer high-level tools built on top of those wrappers. The
safe helpers add dry-runs, confirmation gates, read-only blocking, compact
responses, warnings, blockers and audit events where relevant.

There is intentionally no generic `listmonk_api_request` tool. This keeps path,
method, confirmation, response size and redaction behavior explicit in typed
tools.

Use `listmonk_capability_report` to inspect the active tool surface, hidden
full-mode tools and risk class counts for the running server.
