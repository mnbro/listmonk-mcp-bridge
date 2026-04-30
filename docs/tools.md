# Tool List

Tools are grouped by operational area. The server uses MCP `ToolAnnotations`:

- `read-only`: does not modify Listmonk.
- `mutating`: changes Listmonk state.
- `destructive`: deletes, removes, blocklists, stops or performs destructive-like changes.
- `sensitive read`: requires `confirm_read=true`.
- `send`: sends real email and requires `confirm_send=true`.

## LLM-Friendly Helper Tools

These tools compose existing Listmonk wrappers into safer primitives for LLM agents. They are generic and do not call external systems or encode business-specific workflows.

| Tool | Class | Notes |
| --- | --- | --- |
| `upsert_subscriber_profiles` | mutating | Dry-run first bulk profile sync by email. Merges attributes, preserves existing tags, adds list memberships and writes audit logs for non-dry-run executions. |
| `get_subscriber_context` | read-only | Compact subscriber context by `subscriberId` or `email`, including lists, attributes, tags, status, bounce signals and warnings. |
| `audience_summary` | read-only | Summarizes one or more lists without returning huge subscriber payloads. Includes status counts, attribute coverage, tags and warnings. |
| `personalization_fields_report` | read-only | Reports available personalization fields, coverage, safe fields, risky fields and minimal examples. |
| `validate_message_personalization` | read-only | Detects `{{variable}}` usage in subject/body and reports missing or low-coverage fields. |
| `campaign_risk_check` | read-only | Checks campaign readiness without sending or changing status. Returns blockers, warnings and recommendations. |
| `safe_send_campaign` | send | Runs risk checks, validates optional approval evidence, optionally sends a test, requires `confirmSend=true`, then sends through the existing API wrapper and writes audit logs. |
| `safe_schedule_campaign` | mutating | Runs risk checks, validates optional approval evidence, requires `confirmSchedule=true`, schedules through the existing API wrapper and writes audit logs. |
| `safe_send_transactional_email` | send | Requires `confirmSend=true`, validates recipient input, supports `idempotencyKey`, sends through the existing transactional email wrapper and writes audit logs. |
| `campaign_performance_summary` | read-only | Aggregates available analytics into a compact LLM-friendly summary. Marks unavailable metrics explicitly. |
| `export_engagement_events` | read-only | Best-effort normalized event export. Returns `supported=false` for event types where Listmonk exposes only aggregate data. |
| `export_campaign_markdown` | read-only | Generic campaign Markdown export with optional body and stats. |
| `export_campaign_postmortem_markdown` | read-only | Generic postmortem Markdown based on `campaign_performance_summary`. |
| `export_subscriber_communication_summary` | read-only | Generic subscriber communication summary with structured data and Markdown. |

## Health, Settings and Admin

| Tool | Class | Notes |
| --- | --- | --- |
| `check_listmonk_health` | read-only | Health check. |
| `get_server_config` | sensitive read | Requires `confirm_read=true`. |
| `get_i18n_language` | read-only | Read an i18n language bundle. |
| `get_dashboard_charts` | read-only | Dashboard chart data. |
| `get_dashboard_counts` | read-only | Dashboard counts. |
| `get_settings` | sensitive read | Requires `confirm_read=true`. |
| `update_settings` | mutating | Requires `confirm=true`. |
| `test_smtp_settings` | mutating | Tests SMTP settings. |
| `reload_app` | mutating | Requires `confirm=true`. |
| `get_logs` | sensitive read | Requires `confirm_read=true`. |

## Subscribers

| Tool | Class | Notes |
| --- | --- | --- |
| `get_subscribers` | read-only | Search/list subscribers. |
| `get_subscriber` | read-only | Get one subscriber. |
| `add_subscriber` | mutating | Create subscriber. |
| `update_subscriber` | destructive | Partial update; guarded because it can change status/list membership. |
| `send_subscriber_optin` | send | Requires `confirm_send=true`. |
| `get_subscriber_export` | sensitive read | Requires `confirm_read=true`. |
| `get_subscriber_bounces` | read-only | Subscriber bounce history. |
| `delete_subscriber_bounces` | destructive | Requires `confirm=true`. |
| `blocklist_subscriber` | destructive | Requires `confirm=true`. |
| `manage_subscriber_lists` | destructive | Add/remove/unsubscribe membership; requires `confirm=true`. |
| `blocklist_subscribers` | destructive | Bulk blocklist; requires `confirm=true`. |
| `delete_subscribers_by_query` | destructive | Query-driven bulk delete; confirmed and rate limited. |
| `blocklist_subscribers_by_query` | destructive | Query-driven bulk blocklist; confirmed and rate limited. |
| `manage_subscriber_lists_by_query` | destructive | Query-driven list membership changes; confirmed and rate limited. |
| `remove_subscriber` | destructive | Requires `confirm=true`. |
| `remove_subscribers` | destructive | Bulk remove; requires `confirm=true`. |
| `change_subscriber_status` | destructive | Requires `confirm=true`. |

## Bounces

| Tool | Class | Notes |
| --- | --- | --- |
| `get_bounces` | read-only | List bounces. |
| `get_bounce` | read-only | Get one bounce. |
| `delete_bounce` | destructive | Requires `confirm=true`. |
| `delete_bounces` | destructive | Bulk delete; requires `confirm=true`. |

## Lists

| Tool | Class | Notes |
| --- | --- | --- |
| `get_mailing_lists` | read-only | List mailing lists. |
| `get_public_mailing_lists` | read-only | List public mailing lists. |
| `get_mailing_list` | read-only | Get one mailing list. |
| `create_public_subscription` | mutating | Public subscription flow. |
| `create_mailing_list` | mutating | Create list. |
| `update_mailing_list` | mutating | Update list. |
| `delete_mailing_list` | destructive | Requires `confirm=true`. |
| `delete_mailing_lists` | destructive | Bulk delete; requires `confirm=true`. |
| `get_list_subscribers_tool` | read-only | List subscribers in a list. |

## Imports

| Tool | Class | Notes |
| --- | --- | --- |
| `get_import_subscribers` | read-only | Import status. |
| `get_import_subscriber_logs` | read-only | Import logs. |
| `import_subscribers` | mutating | Upload/import subscribers. |
| `stop_import_subscribers` | destructive | Requires `confirm=true`. |

## Campaigns

| Tool | Class | Notes |
| --- | --- | --- |
| `get_campaigns` | read-only | List campaigns. |
| `get_campaign` | read-only | Get one campaign. |
| `create_campaign` | mutating | Create campaign; can auto-convert plain text to HTML. |
| `update_campaign` | mutating | Update campaign. |
| `send_campaign` | send | Requires `confirm_send=true`. |
| `test_campaign` | send | Requires `confirm_send=true`. |
| `schedule_campaign` | mutating | Schedule send. |
| `update_campaign_status` | mutating | Change campaign status. |
| `delete_campaign` | destructive | Requires `confirm=true`. |
| `delete_campaigns` | destructive | Bulk delete; requires `confirm=true`. |
| `get_campaign_html_preview` | read-only | Read rendered campaign preview. |
| `preview_campaign_body` | read-only | Preview supplied body. |
| `preview_campaign_text` | read-only | Preview supplied text. |
| `get_running_campaign_stats` | read-only | Running campaign stats. |
| `get_campaign_analytics` | read-only | Campaign analytics. |
| `archive_campaign` | mutating | Archive/unarchive campaign. |
| `convert_campaign_content` | mutating | Convert editor/content representation. |
| `replace_in_campaign_body` | mutating | Replace text in campaign body. |
| `regex_replace_in_campaign_body` | mutating | Regex replace in campaign body. |
| `batch_replace_in_campaign_body` | mutating | Batch replace in campaign body. |

## Templates and Transactional Email

| Tool | Class | Notes |
| --- | --- | --- |
| `get_templates` | read-only | List templates. |
| `get_template` | read-only | Get one template. |
| `create_template` | mutating | Create campaign/visual/transactional template. |
| `update_template` | mutating | Update template. |
| `delete_template` | destructive | Requires `confirm=true`. |
| `preview_template` | read-only | Preview template with supplied body. |
| `get_template_html_preview` | read-only | Read rendered template preview. |
| `set_default_template` | mutating | Set default template. |
| `send_transactional_email` | send | Requires `confirm_send=true`. |

## Media

| Tool | Class | Notes |
| --- | --- | --- |
| `get_media_list` | read-only | List media. |
| `get_media_file` | read-only | Get media metadata/file info. |
| `upload_media_file` | mutating | Upload media. |
| `rename_media` | mutating | Rename media. |
| `delete_media_file` | destructive | Requires `confirm=true`. |

## Maintenance

| Tool | Class | Notes |
| --- | --- | --- |
| `delete_gc_subscribers` | destructive | Requires `confirm=true`. |
| `delete_campaign_analytics` | destructive | Requires `confirm=true`. |
| `delete_unconfirmed_subscriptions` | destructive | Requires `confirm=true`. |
