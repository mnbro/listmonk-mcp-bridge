# Safeguards

The server exposes MCP `ToolAnnotations` and runtime guardrails so MCP clients can reason about operational risk and accidental high-impact calls fail closed.

| Operation class | MCP annotation | Runtime requirement |
| --- | --- | --- |
| Strictly read-only tools | `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` | No confirmation, unless the read exposes sensitive data. |
| Sensitive reads | `readOnlyHint=true` | `confirm_read=true`. |
| Destructive or destructive-like operations | `destructiveHint=true` | `confirm=true`. |
| Real email sends | `readOnlyHint=false`, `idempotentHint=false` | `confirm_send=true`. |
| Other side-effecting writes | `readOnlyHint=false`, `idempotentHint=false` | Confirmation where the operation is operationally sensitive. |

## Sensitive Reads

These tools require `confirm_read=true`:

- `get_server_config`
- `get_settings`
- `get_logs`
- `get_subscriber_export`

## Destructive Actions

Destructive tools include delete, remove, blocklist, subscriber list membership changes, GC cleanup, analytics cleanup and stopping imports. They require `confirm=true`.

Query-driven destructive actions are rate limited per process by `LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE`.

## Real Email Sends

These tools require `confirm_send=true`:

- `send_campaign`
- `test_campaign`
- `send_subscriber_optin`
- `send_transactional_email`

## Audit Logging

Confirmed high-impact operations emit structured audit log events on the `listmonk_mcp.audit` logger. Audit context redacts email addresses and secret-like fields, and SQL-like query strings are represented by SHA-256 hashes instead of raw query text.

Rate-limit events are logged on `listmonk_mcp.operations`.

Helper tools that send email, schedule campaigns or run non-dry-run bulk subscriber updates also write JSON audit records under `data/`:

- `data/sync_logs.json`
- `data/send_audit_log.json`
- `data/idempotency_keys.json`

These files are local operational safety state only. They are not a workflow database and do not store external-system concepts.

## Production Notes

- Use HTTPS for your Listmonk instance.
- Use a dedicated API user instead of an admin user.
- Apply least-privilege permissions wherever possible.
- Store credentials in your deployment secret manager, not in source control.
- Rotate API tokens periodically.
- Test campaign-related workflows against a staging Listmonk instance first.
