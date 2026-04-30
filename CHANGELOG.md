# Changelog

## 0.4.6

- Expose transactional email `data` schemas with explicit `anyOf` object/null JSON Schema for connector compatibility.

## [0.4.5](https://github.com/mnbro/listmonk-mcp-bridge/compare/v0.4.4...v0.4.5) (2026-04-30)


### Features

* add comprehensive type annotations for professional-grade code quality ([a563a9a](https://github.com/mnbro/listmonk-mcp-bridge/commit/a563a9ae7bc3545c65d798753fca336d6299898b))
* add data validation layer and campaign management ([2c38840](https://github.com/mnbro/listmonk-mcp-bridge/commit/2c38840703edd0e6574d3cd6fbe2ae333f3b1c09))
* add GitHub Actions workflow for MkDocs Material documentation ([8fc65fe](https://github.com/mnbro/listmonk-mcp-bridge/commit/8fc65fe7d47f6cc9d45fe6e38c78587a7d73ad4e))
* add GitHub Actions workflow for PyPI publishing ([37b3800](https://github.com/mnbro/listmonk-mcp-bridge/commit/37b3800c93afe499b55cd9e63727799345c57d98))
* add proper CLI support with --help and --version flags ([2862844](https://github.com/mnbro/listmonk-mcp-bridge/commit/2862844f4eeb0a41cc0967ffde1289b768e38d57))
* complete list and template management tools and resources ([51f526b](https://github.com/mnbro/listmonk-mcp-bridge/commit/51f526b946388b06adae94924e5f941106a99559))
* media management, discovery tools, campaign editing, and API fixes ([c6f223a](https://github.com/mnbro/listmonk-mcp-bridge/commit/c6f223a4c27a3df8d5f25da5314b91197c007dae))


### Bug Fixes

* auto-fix linting issues with ruff ([00a5a9c](https://github.com/mnbro/listmonk-mcp-bridge/commit/00a5a9c5c004b6397940bb3803fcd1404d59a0a1))
* clean up whitespace and exception handling for linting compliance ([ffbd661](https://github.com/mnbro/listmonk-mcp-bridge/commit/ffbd66154c3514569c3dff000757b3be5b80ee77))
* cleanup resource leak and bump version to 0.1.0 ([2434a3d](https://github.com/mnbro/listmonk-mcp-bridge/commit/2434a3d8fd9b97069136e36b670bc1b42251faba))
* guard docs deploy when pages is disabled ([0c4702a](https://github.com/mnbro/listmonk-mcp-bridge/commit/0c4702a4bcd102892e8f3bad88211d139fbcdb0a))
* install dev dependencies for linting and type checking ([7c279c2](https://github.com/mnbro/listmonk-mcp-bridge/commit/7c279c29f365587ee18c7ef895b765fcd74d74a7))
* remove empty with block from PyPI publish workflow ([f5a9b3c](https://github.com/mnbro/listmonk-mcp-bridge/commit/f5a9b3c3110843619847a290717625bda9893019))
* remove unused client variable in upload_media ([3e1cf0d](https://github.com/mnbro/listmonk-mcp-bridge/commit/3e1cf0d4d4d1dd49b075fa153a633435d0e1f1dd))
* remove uv cache dependency on missing lock file ([6a1a997](https://github.com/mnbro/listmonk-mcp-bridge/commit/6a1a99750b9fd8de14307dbd7e393a7bc12c5bf7))
* repair release workflows ([a1e8903](https://github.com/mnbro/listmonk-mcp-bridge/commit/a1e89030c6e6351e9a3998f4e2338bff8b966fa4))
* resolve all remaining linting issues ([5aff5eb](https://github.com/mnbro/listmonk-mcp-bridge/commit/5aff5eb416e837dc4c1e0ac4b4426219cd99cab8))


### Dependencies

* bump black from 25.1.0 to 26.3.1 ([#7](https://github.com/mnbro/listmonk-mcp-bridge/issues/7)) ([c9351a3](https://github.com/mnbro/listmonk-mcp-bridge/commit/c9351a30dbf31a5b51be05d502beb85171c793b8))
* bump mcp from 1.11.0 to 1.27.0 ([#13](https://github.com/mnbro/listmonk-mcp-bridge/issues/13)) ([2c54a24](https://github.com/mnbro/listmonk-mcp-bridge/commit/2c54a249078e5002615152f5ddc2a41b0e13eb1d))
* bump mkdocs-material from 9.6.16 to 9.7.6 ([#18](https://github.com/mnbro/listmonk-mcp-bridge/issues/18)) ([e2219c6](https://github.com/mnbro/listmonk-mcp-bridge/commit/e2219c68d3db69c4fd62fc52d49d900b34f6b57c))
* bump pydantic-settings from 2.10.1 to 2.14.0 ([#11](https://github.com/mnbro/listmonk-mcp-bridge/issues/11)) ([32863c2](https://github.com/mnbro/listmonk-mcp-bridge/commit/32863c27254a334de50b359388c7c271f0974e35))
* bump pygments from 2.19.2 to 2.20.0 ([#21](https://github.com/mnbro/listmonk-mcp-bridge/issues/21)) ([7f8168c](https://github.com/mnbro/listmonk-mcp-bridge/commit/7f8168cd73f533744cfc32439689b3baa5ef84f1))
* bump pytest from 8.4.1 to 9.0.3 ([#15](https://github.com/mnbro/listmonk-mcp-bridge/issues/15)) ([1cd5ef2](https://github.com/mnbro/listmonk-mcp-bridge/commit/1cd5ef24ad8824523c8147e9ce51230d413be131))
* bump pytest-httpx from 0.35.0 to 0.36.2 ([#16](https://github.com/mnbro/listmonk-mcp-bridge/issues/16)) ([e2365cc](https://github.com/mnbro/listmonk-mcp-bridge/commit/e2365ccef8ca5243c4f62364f6ba50b67c626961))
* bump pytest-mock from 3.14.1 to 3.15.1 ([#10](https://github.com/mnbro/listmonk-mcp-bridge/issues/10)) ([29671bc](https://github.com/mnbro/listmonk-mcp-bridge/commit/29671bcf525ac424afd10d562b2a9729f6ec9aec))
* bump requests from 2.32.4 to 2.33.0 ([#25](https://github.com/mnbro/listmonk-mcp-bridge/issues/25)) ([0cfb72b](https://github.com/mnbro/listmonk-mcp-bridge/commit/0cfb72b5196074ace503b6e1e66765f1da139acc))
* bump ruff from 0.12.3 to 0.15.12 ([#14](https://github.com/mnbro/listmonk-mcp-bridge/issues/14)) ([67be781](https://github.com/mnbro/listmonk-mcp-bridge/commit/67be7810ebce04b3f96441e73b7dde24560a4c21))
* bump typer from 0.16.0 to 0.25.0 ([#19](https://github.com/mnbro/listmonk-mcp-bridge/issues/19)) ([fb3d439](https://github.com/mnbro/listmonk-mcp-bridge/commit/fb3d439fb80ec7ecfd8f8691da6f4ce77c5be026))
* bump urllib3 from 2.5.0 to 2.6.3 ([#26](https://github.com/mnbro/listmonk-mcp-bridge/issues/26)) ([4043844](https://github.com/mnbro/listmonk-mcp-bridge/commit/404384439642672a235cb8b26f3d6c88a95c4ebf))
* update vulnerable Python lockfile dependencies ([d2c0a1a](https://github.com/mnbro/listmonk-mcp-bridge/commit/d2c0a1ae20d83ca997587ca78c1dfa322c401aa6))
* update vulnerable starlette dependency ([9c056cc](https://github.com/mnbro/listmonk-mcp-bridge/commit/9c056cc62754e078a836d816060af1c8dc09f1dd))


### Documentation

* trigger workflow after enabling GitHub Pages ([ff22b5d](https://github.com/mnbro/listmonk-mcp-bridge/commit/ff22b5d1c88cdca33dd4774f2818c18a20e597f0))
* update docs and setup instructions ([a09eb64](https://github.com/mnbro/listmonk-mcp-bridge/commit/a09eb641efacca8a39420eab73110b89f5e0730c))
* update documentation and workflows ([9a75332](https://github.com/mnbro/listmonk-mcp-bridge/commit/9a75332b6d9542e7bdf9f1aed7dcb419ff8b327d))
* update project metadata and README ([7572eda](https://github.com/mnbro/listmonk-mcp-bridge/commit/7572eda58fdde7fa21ed0030063331e090715d46))
* update PyPI project description ([2a603ec](https://github.com/mnbro/listmonk-mcp-bridge/commit/2a603ecdb7b5adc64ffefe0981223be2bbf04e79))
* update README with production-ready positioning ([9207766](https://github.com/mnbro/listmonk-mcp-bridge/commit/9207766fb1ff98ef810a349477b8911ca8b8f2b1))

## 0.4.4

- Expose transactional email `data` schemas as explicit `object | null`.

## 0.4.3

- Improve transactional email data schemas for template variable objects.
- Detect common Listmonk Go template variables in personalization validation.
- Document the `subscribers:sql_query` permission needed for profile upsert email lookup.

## 0.4.2

- Fix Listmonk subscriber list audience helpers to use the general subscriber filter API for valid list IDs.
- Tighten MCP input schemas for LLM helper tools that accept profile arrays and approval/data objects.
- Align runtime package version metadata.

## 0.4.1

- Publish English README examples to PyPI.

## 0.4.0

- Add generic LLM-friendly Listmonk helper tools for profile upsert, subscriber context, audience summaries, personalization validation, campaign risk checks, safe sends/schedules, analytics summaries and exports.
- Add local JSON safety state for generic audit logs, sync logs and transactional email idempotency keys.
- Expand documentation for helper tools while keeping the project scoped to the Listmonk domain.

## 0.3.1

- Split documentation into focused pages for tools, Docker, configuration, API coverage, safeguards and development.
- Simplify MkDocs navigation to match the flat documentation layout.

## 0.3.0

- Add a Debian slim based Docker image for the MCP server.
- Add a GitHub Container Registry publishing workflow and package badge.
- Add container documentation for Docker-based MCP client configuration.

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
