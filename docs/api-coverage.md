# API Coverage

This bridge focuses on the Listmonk API surfaces that are useful for MCP clients and internal automation.

| Area | Covered operations |
| --- | --- |
| Health and admin reads | Health check, server config, settings, logs, i18n language, dashboard charts and counts. |
| Settings/admin writes | Settings update, SMTP settings test, app reload. |
| Subscribers | Search/list, get by ID, create, update, export, bounces, opt-in send, blocklist, delete, status changes and bulk query operations. |
| Lists | List public/all lists, get one list, create/update/delete lists, public subscription and list subscribers. |
| Imports | Import subscribers, get import status, get import logs and stop imports. |
| Campaigns | List/get campaigns, create/update, preview, schedule, status changes, send/test send, archive, delete, content conversion and analytics. |
| Templates | List/get, create/update/delete, preview, HTML preview and default template selection. |
| Transactional email | Send transactional email to one or more subscribers with confirmation. |
| Media | List/get, upload, rename and delete media files. |
| Maintenance | Subscriber GC cleanup, campaign analytics cleanup and unconfirmed subscription cleanup. |
| MCP resources | Subscriber, campaign, list, template and media resource views. |
| LLM-friendly helpers | Generic subscriber profile sync, subscriber context, audience summaries, personalization validation, campaign risk checks, safe sends/schedules, analytics summaries and Markdown/event exports. |

## Coverage Notes

- The bridge is intentionally not read-only. It includes mutating and destructive Listmonk workflows, but every high-impact operation is annotated and guarded.
- Tools keep Listmonk naming and behavior visible where it matters, while adding MCP-friendly validation and structured responses.
- Query-driven destructive subscriber operations are rate limited to reduce accidental large-scale changes.
- Helper tools compose existing Listmonk wrappers. They do not integrate external systems or encode cross-system workflows.

## Response Shape

Successful tools return structured dictionaries with `success=true` or the raw Listmonk response wrapped by the client. Errors are normalized by the server so MCP clients do not receive raw tracebacks.
