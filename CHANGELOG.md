# Changelog

## Unreleased

- Rewrite the runtime implementation around a compact Listmonk API client and explicit MCP safety guardrails.
- Change project licensing to PolyForm Internal Use License 1.0.0.
- Remove optional Nix flake development infrastructure and CI checks.
- Update GitHub Pages documentation deployment to support manual dispatch after Pages is enabled.

## 0.2.0

- Rewrite the runtime implementation around a compact Listmonk API client and explicit MCP safety guardrails.
- Change project licensing to PolyForm Internal Use License 1.0.0.

## [0.1.13](https://github.com/mnbro/listmonk-mcp-bridge/compare/v0.1.12...v0.1.13) (2026-04-28)


### Dependencies

* update vulnerable starlette dependency ([9c056cc](https://github.com/mnbro/listmonk-mcp-bridge/commit/9c056cc62754e078a836d816060af1c8dc09f1dd))

## [0.1.12](https://github.com/mnbro/listmonk-mcp-bridge/compare/v0.1.11...v0.1.12) (2026-04-28)


### Dependencies

* update vulnerable Python lockfile dependencies ([d2c0a1a](https://github.com/mnbro/listmonk-mcp-bridge/commit/d2c0a1ae20d83ca997587ca78c1dfa322c401aa6))

## [0.1.11](https://github.com/mnbro/listmonk-mcp-bridge/compare/v0.1.10...v0.1.11) (2026-04-28)


### Dependencies

* bump pygments from 2.19.2 to 2.20.0 ([#21](https://github.com/mnbro/listmonk-mcp-bridge/issues/21)) ([7f8168c](https://github.com/mnbro/listmonk-mcp-bridge/commit/7f8168cd73f533744cfc32439689b3baa5ef84f1))
* bump requests from 2.32.4 to 2.33.0 ([#25](https://github.com/mnbro/listmonk-mcp-bridge/issues/25)) ([0cfb72b](https://github.com/mnbro/listmonk-mcp-bridge/commit/0cfb72b5196074ace503b6e1e66765f1da139acc))
* bump urllib3 from 2.5.0 to 2.6.3 ([#26](https://github.com/mnbro/listmonk-mcp-bridge/issues/26)) ([4043844](https://github.com/mnbro/listmonk-mcp-bridge/commit/404384439642672a235cb8b26f3d6c88a95c4ebf))

## [0.1.10](https://github.com/mnbro/listmonk-mcp-bridge/compare/v0.1.9...v0.1.10) (2026-04-28)


### Dependencies

* bump black from 25.1.0 to 26.3.1 ([#7](https://github.com/mnbro/listmonk-mcp-bridge/issues/7)) ([c9351a3](https://github.com/mnbro/listmonk-mcp-bridge/commit/c9351a30dbf31a5b51be05d502beb85171c793b8))
* bump mcp from 1.11.0 to 1.27.0 ([#13](https://github.com/mnbro/listmonk-mcp-bridge/issues/13)) ([2c54a24](https://github.com/mnbro/listmonk-mcp-bridge/commit/2c54a249078e5002615152f5ddc2a41b0e13eb1d))
* bump mkdocs-material from 9.6.16 to 9.7.6 ([#18](https://github.com/mnbro/listmonk-mcp-bridge/issues/18)) ([e2219c6](https://github.com/mnbro/listmonk-mcp-bridge/commit/e2219c68d3db69c4fd62fc52d49d900b34f6b57c))
* bump pydantic-settings from 2.10.1 to 2.14.0 ([#11](https://github.com/mnbro/listmonk-mcp-bridge/issues/11)) ([32863c2](https://github.com/mnbro/listmonk-mcp-bridge/commit/32863c27254a334de50b359388c7c271f0974e35))
* bump pytest from 8.4.1 to 9.0.3 ([#15](https://github.com/mnbro/listmonk-mcp-bridge/issues/15)) ([1cd5ef2](https://github.com/mnbro/listmonk-mcp-bridge/commit/1cd5ef24ad8824523c8147e9ce51230d413be131))
* bump pytest-httpx from 0.35.0 to 0.36.2 ([#16](https://github.com/mnbro/listmonk-mcp-bridge/issues/16)) ([e2365cc](https://github.com/mnbro/listmonk-mcp-bridge/commit/e2365ccef8ca5243c4f62364f6ba50b67c626961))
* bump pytest-mock from 3.14.1 to 3.15.1 ([#10](https://github.com/mnbro/listmonk-mcp-bridge/issues/10)) ([29671bc](https://github.com/mnbro/listmonk-mcp-bridge/commit/29671bcf525ac424afd10d562b2a9729f6ec9aec))
* bump ruff from 0.12.3 to 0.15.12 ([#14](https://github.com/mnbro/listmonk-mcp-bridge/issues/14)) ([67be781](https://github.com/mnbro/listmonk-mcp-bridge/commit/67be7810ebce04b3f96441e73b7dde24560a4c21))
* bump typer from 0.16.0 to 0.25.0 ([#19](https://github.com/mnbro/listmonk-mcp-bridge/issues/19)) ([fb3d439](https://github.com/mnbro/listmonk-mcp-bridge/commit/fb3d439fb80ec7ecfd8f8691da6f4ce77c5be026))

## 0.1.9

- Add automated dependency update PRs for uv and GitHub Actions.
- Add auto-merge workflow for successful bot dependency update PRs.

## 0.1.8

- Update README production, guardrail, audit logging, rate limiting, and staging smoke-test documentation to match current server behavior.

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
