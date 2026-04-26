# Changelog

## 0.1.7

- Require `confirm_read=true` for sensitive read tools that expose settings, logs, server config, or full subscriber exports.
- Redact email addresses and raw SQL-like query strings from audit logs while retaining query hashes for correlation.

## 0.1.6

- Add structured audit logging for confirmed destructive and email-sending operations.
- Add per-process rate limiting and observability logs for query-driven bulk operations.
- Add opt-in staging smoke tests for settings updates, subscriber imports, and campaign test email sends.
- Expand automated guardrail tests to exercise every confirmation path.

## 0.1.5

- Require `confirm_send=true` before tools send real email.
- Add conditional confirmation for subscriber list removals, unsubscribe actions, blocklist status changes, sensitive subscriber updates, settings updates, app reloads, and stopping imports.
- Add explicit read-only annotations for read-only tools.

## 0.1.4

- Add MCP annotations for destructive and email-sending tools so clients can surface side-effect risk.
- Require `confirm=true` before destructive tools delete, remove, blocklist, garbage collect, or clean analytics data.
- Add regression coverage for destructive guardrails and email-sending tool annotations.

## 0.1.3

- Emit explicit MCP JSON schemas for complex tool arguments used by settings, SMTP testing, subscriber import, and batch campaign body replacement tools.
- Add regression coverage for documented MCP tool argument schemas.

## 0.1.2

- Use Listmonk's partial subscriber update endpoint (`PATCH /api/subscribers/{id}`) so updating only `name`, `status`, `lists`, or `attributes` does not require an `email`.
- Align package and runtime version metadata.

## 0.1.1

- Align MCP tools with the complete Listmonk Swagger API.
- Expose all 72 Listmonk Swagger operations as MCP tools, plus focused convenience workflows.
- Add tools for settings, admin reload, logs, dashboard data, public subscriptions, imports, bounces, maintenance cleanup, and campaign/template preview operations.
- Extend campaign, template, transactional, subscriber, list, and media payloads to match Listmonk API fields.
- Fix partial subscriber updates so omitted fields are not sent.
- Require and send template `subject`, including transactional template support.
- Add plain text to HTML campaign body conversion with explicit `auto_convert_plain_to_html` behavior.
- Add regression tests for Swagger endpoint paths, payloads, template creation, subscriber partial updates, and plain text normalization.

## 0.1.0

- Initial public package release.
