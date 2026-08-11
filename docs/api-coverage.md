# API Coverage

This bridge focuses on the Listmonk API surfaces that are useful for MCP clients and internal automation.

The route and payload contract was last audited on 2026-08-11 against
[Listmonk v6.2.0](https://github.com/knadh/listmonk/tree/v6.2.0) and current
upstream commit
[`d946ce5`](https://github.com/knadh/listmonk/tree/d946ce543f90d77caf751efab54ab86f94127e14).

The exact content-addressed API contract and bridge release compatibility
history are published in the [Listmonk API compatibility matrix](compatibility.md).
Scheduled automation checks new stable Listmonk releases and requires an explicit
implementation or omission decision for every new route.

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
| Media | List/get, upload and delete media files. |
| Maintenance | Subscriber GC cleanup, campaign analytics cleanup and unconfirmed subscription cleanup. |
| MCP resources | Subscriber, campaign, list, template and media resource views. |
| LLM-friendly helpers | Generic subscriber profile sync, subscriber context, audience summaries, personalization validation, campaign risk checks, safe test/send/schedule helpers, analytics summaries and Markdown/event exports. |

## Coverage Notes

- The bridge is intentionally not read-only. It includes mutating and destructive Listmonk workflows, but every high-impact operation is annotated and guarded.
- Tools keep Listmonk naming and behavior visible where it matters, while adding MCP-friendly validation and structured responses.
- Query-driven destructive subscriber operations are rate limited to reduce accidental large-scale changes.
- Helper tools compose existing Listmonk wrappers. They do not integrate external systems or encode cross-system workflows.
- Listmonk's media API has no update or rename endpoint. `upload_media_file.title`
  controls the multipart filename for a new upload; existing media can only be read
  or deleted.
- Listmonk analytics endpoints return aggregate time buckets, not subscriber-level
  events. `export_engagement_events` reports this limitation instead of presenting
  aggregates as individual events.
- Partial campaign, list and template updates first load the current object and send
  the complete Listmonk `PUT` representation, preserving relationships and required
  fields that Listmonk would otherwise clear or reject.
- Campaign creation always creates a draft. Listmonk does not consume a
  `send_later` field, so scheduling is exposed only through the explicit scheduling
  tools. Campaign listing exposes the filters the handler actually consumes rather
  than the ignored `type` parameter from older bridge versions.
- Template default selection is composed through Listmonk's dedicated default
  endpoint. Template body preview uses the stored template type; Listmonk has no
  preview `content_type` parameter.
- Content conversion returns converted content without persisting the campaign and
  is therefore exposed as read-only.

## Response Shape

Successful tools return structured dictionaries with `success=true` or the raw Listmonk response wrapped by the client. Errors are normalized by the server so MCP clients do not receive raw tracebacks.
