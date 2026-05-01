"""FastMCP server for Listmonk with explicit safety guardrails."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

import typer
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from .client import (
    ListmonkAPIError,
    ListmonkClient,
    compact_payload,
    extract_campaign_list_ids,
    listmonk_query_string_literal,
)
from .config import Config
from .config import get_config as load_runtime_config
from .exceptions import ResourceNotFoundError, safe_execute_async

audit_logger = logging.getLogger("listmonk_mcp.audit")
operations_logger = logging.getLogger("listmonk_mcp.operations")
logger = logging.getLogger(__name__)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
MUTATING = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


SettingsPayload = Annotated[
    dict[str, Any],
    Field(description="Listmonk settings object"),
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "app": {"type": "object"},
                "privacy": {"type": "object"},
                "smtp": {"type": "object"},
                "messengers": {"type": "object"},
                "bounce": {"type": "object"},
                "media": {"type": "object"},
                "security": {"type": "object"},
                "performance": {"type": "object"},
                "appearance": {"type": "object"},
            },
            "additionalProperties": True,
        }
    ),
]
SmtpSettingsPayload = Annotated[
    dict[str, Any],
    Field(description="SMTP settings object"),
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "auth_protocol": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "tls_type": {"type": "string"},
                "tls_skip_verify": {"type": "boolean"},
            },
            "additionalProperties": True,
        }
    ),
]
SubscriberProfilesPayload = Annotated[
    list[dict[str, Any]],
    Field(description="Subscriber profiles to create or update by email."),
    WithJsonSchema(
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["email"],
                "properties": {
                    "externalId": {"type": "string"},
                    "source": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                    "name": {"type": "string"},
                    "attributes": {"type": "object", "additionalProperties": True},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "listIds": {"type": "array", "items": {"type": "integer"}},
                    "status": {
                        "type": "string",
                        "enum": ["enabled", "disabled", "blocklisted"],
                    },
                },
                "additionalProperties": True,
            },
        }
    ),
]
ApprovalPayload = Annotated[
    dict[str, Any],
    Field(description="External approval evidence supplied by an orchestrator."),
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "required": {"type": "boolean"},
                "status": {"type": "string"},
                "approvalId": {"type": "string"},
            },
            "additionalProperties": True,
        }
    ),
]
TransactionalDataPayload = Annotated[
    dict[str, Any],
    Field(
        description="Template data object for Listmonk transactional email rendering."
    ),
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Optional example personalization field.",
                },
                "customMessage": {
                    "type": "string",
                    "description": "Optional example personalization field.",
                },
            },
            "additionalProperties": True,
        }
    ),
]
TestRecipientsPayload = Annotated[
    list[str],
    Field(description="Recipient email addresses for a Listmonk campaign test send."),
    WithJsonSchema(
        {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            "minItems": 1,
        }
    ),
]
ImportSubscriberParamsPayload = Annotated[
    dict[str, Any],
    Field(description="Subscriber import parameters"),
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["subscribe", "blocklist"]},
                "delim": {"type": "string", "minLength": 1, "maxLength": 1},
                "lists": {"type": "array", "items": {"type": "integer"}},
                "overwrite": {"type": "boolean"},
                "subscription_status": {"type": "string"},
            },
            "required": ["mode", "delim"],
            "additionalProperties": True,
        }
    ),
]
CampaignBodyReplacementsPayload = Annotated[
    list[dict[str, str]],
    Field(description="Campaign body search-and-replace operations"),
    WithJsonSchema(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "search": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["search", "replace"],
                "additionalProperties": False,
            },
        }
    ),
]


@asynccontextmanager
async def lifespan(app: Any) -> Any:
    yield


mcp = FastMCP(name="listmonk-mcp-bridge", lifespan=lifespan)
_client: ListmonkClient | None = None
_bulk_query_events: deque[float] = deque()
_template_variable_pattern = re.compile(r"{{\s*([^{}]+?)\s*}}")
_email_pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_data_dir = Path("data")
_sync_log_path = _data_dir / "sync_logs.json"
_send_audit_log_path = _data_dir / "send_audit_log.json"
_idempotency_keys_path = _data_dir / "idempotency_keys.json"


def create_production_server() -> FastMCP:
    return mcp


def get_config() -> Config:
    return load_runtime_config()


def get_client() -> ListmonkClient:
    global _client
    if _client is None:
        _client = ListmonkClient(get_config())
    return _client


def success_response(message: str, **data: Any) -> dict[str, Any]:
    return {"success": True, "message": message, **data}


def collection_response(
    resource: str,
    items: list[dict[str, Any]],
    *,
    total: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "success": True,
        "resource": resource,
        "count": len(items),
        "items": items,
    }
    if total is not None:
        response["total"] = total
    if page is not None:
        response["page"] = page
    if per_page is not None:
        response["per_page"] = per_page
    return response


def _hash_sensitive_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _redact_audit_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if "query" in lowered and isinstance(value, str):
        return {"sha256": _hash_sensitive_text(value)}
    if isinstance(value, str) and re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return "<redacted-email>"
    if any(
        marker in lowered for marker in ("password", "token", "secret", "authorization")
    ):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            item_key: _redact_audit_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_audit_value(key, item) for item in value]
    return value


def audit_confirmed_operation(kind: str, operation: str, **context: Any) -> None:
    redacted = {key: _redact_audit_value(key, value) for key, value in context.items()}
    audit_logger.warning(
        "confirmed_operation %s",
        json.dumps(
            {"kind": kind, "operation": operation, "context": redacted}, sort_keys=True
        ),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _append_json_log(path: Path, entry: dict[str, Any]) -> None:
    current = _read_json_file(path, [])
    entries = current if isinstance(current, list) else []
    entries.append(entry)
    _write_json_file(path, entries)


def write_safety_audit_log(
    tool_name: str,
    entity_type: str,
    entity_id: str,
    action: str,
    input_summary: dict[str, Any],
    result: dict[str, Any],
    warnings: list[str] | None = None,
) -> str:
    audit_id = f"audit-{uuid4().hex}"
    entry = {
        "auditId": audit_id,
        "toolName": tool_name,
        "entityType": entity_type,
        "entityId": entity_id,
        "action": action,
        "inputSummary": _redact_audit_value("inputSummary", input_summary),
        "result": _redact_audit_value("result", result),
        "warnings": warnings or [],
        "createdAt": _utc_now_iso(),
    }
    _append_json_log(_send_audit_log_path, entry)
    audit_logger.warning("safety_audit %s", json.dumps(entry, sort_keys=True))
    return audit_id


def _normalize_listmonk_response(response: dict[str, Any]) -> Any:
    return response.get("data", response)


def _results_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = _normalize_listmonk_response(response)
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _one_from_response(response: dict[str, Any]) -> dict[str, Any] | None:
    data = _normalize_listmonk_response(response)
    return data if isinstance(data, dict) else None


def _subscriber_attribs(subscriber: dict[str, Any]) -> dict[str, Any]:
    attribs = subscriber.get("attribs", subscriber.get("attributes", {}))
    return attribs if isinstance(attribs, dict) else {}


def _subscriber_tags(subscriber: dict[str, Any]) -> list[str]:
    raw_tags = subscriber.get("tags", [])
    return [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []


def _subscriber_lists(subscriber: dict[str, Any]) -> list[dict[str, Any]]:
    raw_lists = subscriber.get("lists", [])
    if not isinstance(raw_lists, list):
        return []
    return [item for item in raw_lists if isinstance(item, dict)]


def _list_ids_from_subscriber(subscriber: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for item in _subscriber_lists(subscriber):
        value = item.get("id")
        if isinstance(value, int):
            ids.append(value)
    return ids


def _extract_campaign_list_ids(campaign: dict[str, Any]) -> list[int]:
    return extract_campaign_list_ids(campaign)


def _email_recipient_blockers(recipients: list[str]) -> list[str]:
    blockers: list[str] = []
    if not recipients:
        blockers.append("At least one recipient email address is required")
    for recipient in recipients:
        if not isinstance(recipient, str) or not _email_pattern.fullmatch(recipient):
            blockers.append(f"Invalid email recipient: {recipient}")
    return blockers


def _int_field(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


async def _lookup_subscriber_by_email(email: str) -> dict[str, Any] | None:
    client = get_client()
    if hasattr(client, "get_subscriber_by_email"):
        response = await client.get_subscriber_by_email(email)
        found = _one_from_response(response)
        if found is not None:
            return found
    response = await client.get_subscribers(
        query=f"subscribers.email = {listmonk_query_string_literal(email)}"
    )
    results = _results_from_response(response)
    return results[0] if results else None


async def _lookup_subscriber(
    subscriber_id: int | None = None, email: str | None = None
) -> dict[str, Any] | None:
    if subscriber_id is not None:
        response = await get_client().get_subscriber(subscriber_id)
        return _one_from_response(response)
    if email:
        return await _lookup_subscriber_by_email(email)
    return None


async def _collect_audience_subscribers(
    list_ids: list[int], sample_size: int = 500
) -> list[dict[str, Any]]:
    subscribers_by_id: dict[str, dict[str, Any]] = {}
    for list_id in list_ids:
        response = await _get_subscribers_for_list(
            list_id, page=1, per_page=sample_size
        )
        for subscriber in _results_from_response(response):
            key = str(subscriber.get("id") or subscriber.get("email") or uuid4().hex)
            subscribers_by_id[key] = subscriber
    return list(subscribers_by_id.values())


async def _get_subscribers_for_list(
    list_id: int, page: int = 1, per_page: int = 20
) -> dict[str, Any]:
    client = get_client()
    if hasattr(client, "get_subscribers"):
        try:
            return await client.get_subscribers(
                page=page,
                per_page=per_page,
                list_ids=[list_id],
            )
        except TypeError:
            pass
    return await client.get_list_subscribers(list_id, page, per_page)


def _attribute_coverage(
    subscribers: list[dict[str, Any]], fields: list[str] | None = None
) -> dict[str, float]:
    discovered: set[str] = set(fields or [])
    for subscriber in subscribers:
        discovered.update(str(key) for key in _subscriber_attribs(subscriber))
        if subscriber.get("name") is not None:
            discovered.add("name")
    if not subscribers:
        return dict.fromkeys(sorted(discovered), 0.0)
    coverage: dict[str, float] = {}
    for field in sorted(discovered):
        present = 0
        for subscriber in subscribers:
            value = (
                subscriber.get("name")
                if field == "name"
                else subscriber.get("email")
                if field == "email"
                else _subscriber_attribs(subscriber).get(field)
            )
            if value not in (None, ""):
                present += 1
        coverage[field] = round(present / len(subscribers), 4)
    return coverage


def _extract_template_variables(*texts: str | None) -> list[str]:
    variables: set[str] = set()
    for text in texts:
        if text:
            for match in _template_variable_pattern.finditer(text):
                normalized = _normalize_template_variable(match.group(1))
                if normalized:
                    variables.add(normalized)
    return sorted(variables)


def _normalize_template_variable(expression: str) -> str | None:
    value = expression.strip()
    if not value:
        return None
    if value.startswith(".Campaign."):
        return None
    if value == ".Subscriber.Name":
        return "name"
    if value == ".Subscriber.Email":
        return "email"
    attrib_prefix = ".Subscriber.Attribs."
    if value.startswith(attrib_prefix):
        field = value.removeprefix(attrib_prefix).strip()
        return field or None
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.-]*", value):
        return value
    return None


def _risk_level(warnings: list[str], blockers: list[str]) -> str:
    if blockers:
        return "high"
    if warnings:
        return "medium"
    return "low"


def _approval_blocker(approval: dict[str, Any] | None) -> str | None:
    if not approval or not approval.get("required"):
        return None
    if approval.get("status") != "approved":
        return "Approval is required but approval.status is not approved"
    return None


def confirmation_required(
    confirm: bool, operation: str, **context: Any
) -> dict[str, Any] | None:
    if confirm:
        audit_confirmed_operation("confirmed", operation, **context)
        return None
    return {
        "success": False,
        "error": {
            "error_type": "ConfirmationRequired",
            "message": f"Set confirm=true to run operation: {operation}",
            "operation": operation,
            "confirm_required": True,
            "context": context,
        },
    }


def read_confirmation_required(
    confirm_read: bool, operation: str, **context: Any
) -> dict[str, Any] | None:
    if confirm_read:
        audit_confirmed_operation("confirmed_read", operation, **context)
        return None
    return {
        "success": False,
        "error": {
            "error_type": "ReadConfirmationRequired",
            "message": f"Set confirm_read=true to run sensitive read: {operation}",
            "operation": operation,
            "confirm_required": True,
            "context": context,
        },
    }


def send_confirmation_required(
    confirm_send: bool, operation: str, **context: Any
) -> dict[str, Any] | None:
    if confirm_send:
        audit_confirmed_operation("confirmed_send", operation, **context)
        return None
    return {
        "success": False,
        "error": {
            "error_type": "SendConfirmationRequired",
            "message": f"Set confirm_send=true to run email-sending operation: {operation}",
            "operation": operation,
            "confirm_required": True,
            "context": context,
        },
    }


def get_bulk_query_rate_limit_per_minute() -> int:
    raw = os.getenv("LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE", "30")
    try:
        return max(int(raw), 0)
    except ValueError:
        logger.warning(
            "Invalid LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE=%r; using 30", raw
        )
        return 30


def check_bulk_query_rate_limit(
    operation: str, query: str | None = None
) -> dict[str, Any] | None:
    limit = get_bulk_query_rate_limit_per_minute()
    if limit == 0:
        return None
    now = time.monotonic()
    while _bulk_query_events and now - _bulk_query_events[0] >= 60:
        _bulk_query_events.popleft()
    if len(_bulk_query_events) >= limit:
        operations_logger.info(
            "bulk_query_rate_limited operation=%s query_sha256=%s",
            operation,
            _hash_sensitive_text(query or ""),
        )
        return {
            "success": False,
            "error": {
                "error_type": "RateLimitExceeded",
                "message": "Bulk query operation rate limit exceeded",
                "operation": operation,
                "retry_after_seconds": 60,
            },
        }
    _bulk_query_events.append(now)
    operations_logger.info(
        "bulk_query_operation_allowed operation=%s query_sha256=%s",
        operation,
        _hash_sensitive_text(query or ""),
    )
    return None


async def _call(operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    result = await safe_execute_async(operation)
    if not isinstance(result, dict):
        return {"success": True, "data": result}
    if "success" in result:
        return result
    return {"success": True, **result}


def _data_items(response: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    data = response.get("data", response)
    if isinstance(data, dict):
        results = data.get("results", data.get("items", []))
        if isinstance(results, list):
            return [
                item if isinstance(item, dict) else {"value": item} for item in results
            ], data.get("total")
    if isinstance(data, list):
        return [
            item if isinstance(item, dict) else {"value": item} for item in data
        ], len(data)
    return [], None


@mcp.tool(annotations=READ_ONLY)
async def check_listmonk_health() -> dict[str, Any]:
    return await _call(lambda: get_client().health_check())


@mcp.tool(annotations=READ_ONLY)
async def get_server_config(confirm_read: bool = False) -> dict[str, Any]:
    if blocked := read_confirmation_required(confirm_read, "get server config"):
        return blocked
    return await _call(lambda: get_client().get_server_config())


@mcp.tool(annotations=READ_ONLY)
async def get_i18n_language(lang: str) -> dict[str, Any]:
    return await _call(lambda: get_client().get_i18n_language(lang))


@mcp.tool(annotations=READ_ONLY)
async def get_dashboard_charts() -> dict[str, Any]:
    return await _call(lambda: get_client().get_dashboard_charts())


@mcp.tool(annotations=READ_ONLY)
async def get_dashboard_counts() -> dict[str, Any]:
    return await _call(lambda: get_client().get_dashboard_counts())


@mcp.tool(annotations=READ_ONLY)
async def get_settings(confirm_read: bool = False) -> dict[str, Any]:
    if blocked := read_confirmation_required(confirm_read, "get settings"):
        return blocked
    return await _call(lambda: get_client().get_settings())


@mcp.tool(annotations=MUTATING)
async def update_settings(
    settings: SettingsPayload, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(confirm, "update settings"):
        return blocked
    return await _call(lambda: get_client().update_settings(settings))


@mcp.tool(annotations=MUTATING)
async def test_smtp_settings(settings: SmtpSettingsPayload) -> dict[str, Any]:
    return await _call(lambda: get_client().test_smtp_settings(settings))


@mcp.tool(annotations=MUTATING)
async def reload_app(confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(confirm, "reload app"):
        return blocked
    return await _call(lambda: get_client().reload_app())


@mcp.tool(annotations=READ_ONLY)
async def get_logs(confirm_read: bool = False) -> dict[str, Any]:
    if blocked := read_confirmation_required(confirm_read, "get logs"):
        return blocked
    return await _call(lambda: get_client().get_logs())


@mcp.tool(annotations=READ_ONLY)
async def get_subscribers(
    page: int = 1,
    per_page: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
    query: str | None = None,
    subscription_status: str | None = None,
    list_ids: list[int] | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().get_subscribers(
            page, per_page, order_by, order, query, subscription_status, list_ids
        )
    )


@mcp.tool(annotations=READ_ONLY)
async def get_subscriber(subscriber_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_subscriber(subscriber_id))


@mcp.tool(annotations=MUTATING)
async def add_subscriber(
    email: str,
    name: str,
    status: str = "enabled",
    lists: list[int] | None = None,
    attribs: dict[str, Any] | None = None,
    preconfirm_subscriptions: bool = False,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().create_subscriber(
            email, name, status, lists, attribs, preconfirm_subscriptions
        )
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def update_subscriber(
    subscriber_id: int,
    email: str | None = None,
    name: str | None = None,
    status: str | None = None,
    lists: list[int] | None = None,
    attribs: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "update subscriber", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(
        lambda: get_client().update_subscriber(
            subscriber_id, email, name, status, lists, None, attribs
        )
    )


@mcp.tool(annotations=MUTATING)
async def send_subscriber_optin(
    subscriber_id: int, confirm_send: bool = False
) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send, "send subscriber optin", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(lambda: get_client().send_subscriber_optin(subscriber_id))


@mcp.tool(annotations=READ_ONLY)
async def get_subscriber_export(
    subscriber_id: int, confirm_read: bool = False
) -> dict[str, Any]:
    if blocked := read_confirmation_required(
        confirm_read, "get subscriber export", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(lambda: get_client().get_subscriber_export(subscriber_id))


@mcp.tool(annotations=READ_ONLY)
async def get_subscriber_bounces(subscriber_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_subscriber_bounces(subscriber_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_subscriber_bounces(
    subscriber_id: int, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete subscriber bounces", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_subscriber_bounces(subscriber_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def blocklist_subscriber(
    subscriber_id: int, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "blocklist subscriber", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(lambda: get_client().blocklist_subscriber(subscriber_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def manage_subscriber_lists(
    action: str,
    target_list_ids: list[int],
    subscriber_ids: list[int],
    status: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm,
        "manage subscriber lists",
        action=action,
        target_list_ids=target_list_ids,
        subscriber_ids=subscriber_ids,
    ):
        return blocked
    return await _call(
        lambda: get_client().manage_subscriber_lists(
            action, target_list_ids, subscriber_ids=subscriber_ids, status=status
        )
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def blocklist_subscribers(
    subscriber_ids: list[int], confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "blocklist subscribers", subscriber_ids=subscriber_ids
    ):
        return blocked
    return await _call(
        lambda: get_client().blocklist_subscribers(subscriber_ids=subscriber_ids)
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_subscribers_by_query(
    query: str, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete subscribers by query", query=query
    ):
        return blocked
    if limited := check_bulk_query_rate_limit("delete subscribers by query", query):
        return limited
    return await _call(lambda: get_client().delete_subscribers_by_query(query))


@mcp.tool(annotations=DESTRUCTIVE)
async def blocklist_subscribers_by_query(
    query: str, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "blocklist subscribers by query", query=query
    ):
        return blocked
    if limited := check_bulk_query_rate_limit("blocklist subscribers by query", query):
        return limited
    return await _call(lambda: get_client().blocklist_subscribers_by_query(query))


@mcp.tool(annotations=DESTRUCTIVE)
async def manage_subscriber_lists_by_query(
    query: str,
    action: str,
    target_list_ids: list[int],
    status: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm,
        "manage subscriber lists by query",
        query=query,
        action=action,
        target_list_ids=target_list_ids,
    ):
        return blocked
    if limited := check_bulk_query_rate_limit(
        "manage subscriber lists by query", query
    ):
        return limited
    return await _call(
        lambda: get_client().manage_subscriber_lists_by_query(
            query, action, target_list_ids, status
        )
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def remove_subscriber(
    subscriber_id: int, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "remove subscriber", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_subscriber(subscriber_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def remove_subscribers(
    subscriber_ids: list[int], confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "remove subscribers", subscriber_ids=subscriber_ids
    ):
        return blocked
    return await _call(lambda: get_client().delete_subscribers(subscriber_ids))


@mcp.tool(annotations=DESTRUCTIVE)
async def change_subscriber_status(
    subscriber_id: int, status: str, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "change subscriber status", subscriber_id=subscriber_id
    ):
        return blocked
    return await _call(
        lambda: get_client().set_subscriber_status(subscriber_id, status)
    )


@mcp.tool(annotations=READ_ONLY)
async def get_bounces(
    page: int = 1,
    per_page: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
    campaign_id: int | None = None,
    subscriber_id: int | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().get_bounces(
            page, per_page, order_by, order, campaign_id, subscriber_id
        )
    )


@mcp.tool(annotations=READ_ONLY)
async def get_bounce(bounce_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_bounce(bounce_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_bounce(bounce_id: int, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(confirm, "delete bounce", bounce_id=bounce_id):
        return blocked
    return await _call(lambda: get_client().delete_bounce(bounce_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_bounces(
    bounce_ids: list[int], confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete bounces", bounce_ids=bounce_ids
    ):
        return blocked
    return await _call(lambda: get_client().delete_bounces(bounce_ids))


@mcp.tool(annotations=READ_ONLY)
async def get_mailing_lists(
    page: int = 1,
    per_page: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
    query: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().get_lists(page, per_page, order_by, order, query)
    )


@mcp.tool(annotations=READ_ONLY)
async def get_public_mailing_lists() -> dict[str, Any]:
    return await _call(lambda: get_client().get_public_lists())


@mcp.tool(annotations=READ_ONLY)
async def get_mailing_list(list_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_list(list_id))


@mcp.tool(annotations=MUTATING)
async def create_public_subscription(
    name: str, email: str, list_uuids: list[str]
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().create_public_subscription(name, email, list_uuids)
    )


@mcp.tool(annotations=MUTATING)
async def create_mailing_list(
    name: str,
    type: str = "public",
    optin: str = "single",
    tags: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().create_list(name, type, optin, tags, description)
    )


@mcp.tool(annotations=MUTATING)
async def update_mailing_list(
    list_id: int,
    name: str | None = None,
    type: str | None = None,
    optin: str | None = None,
    tags: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().update_list(list_id, name, type, optin, tags, description)
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_mailing_list(list_id: int, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete mailing list", list_id=list_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_list(list_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_mailing_lists(
    list_ids: list[int], confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete mailing lists", list_ids=list_ids
    ):
        return blocked
    return await _call(lambda: get_client().delete_lists(list_ids=list_ids))


@mcp.tool(annotations=READ_ONLY)
async def get_import_subscribers() -> dict[str, Any]:
    return await _call(lambda: get_client().get_import_subscribers())


@mcp.tool(annotations=READ_ONLY)
async def get_import_subscriber_logs() -> dict[str, Any]:
    return await _call(lambda: get_client().get_import_subscriber_logs())


@mcp.tool(annotations=MUTATING)
async def import_subscribers(
    file_path: str, params: ImportSubscriberParamsPayload
) -> dict[str, Any]:
    return await _call(lambda: get_client().import_subscribers(file_path, params))


@mcp.tool(annotations=DESTRUCTIVE)
async def stop_import_subscribers(confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(confirm, "stop import subscribers"):
        return blocked
    return await _call(lambda: get_client().stop_import_subscribers())


@mcp.tool(annotations=READ_ONLY)
async def get_list_subscribers_tool(
    list_id: int, page: int = 1, per_page: int = 20
) -> dict[str, Any]:
    response = await _get_subscribers_for_list(list_id, page, per_page)
    items, total = _data_items(response)
    return {
        "success": True,
        "list_id": list_id,
        "page": page,
        "per_page": per_page,
        "count": len(items),
        "total": total,
        "subscribers": items,
    }


@mcp.tool(annotations=READ_ONLY)
async def get_campaigns(
    page: int = 1,
    per_page: int = 20,
    order_by: str = "created_at",
    order: str = "desc",
    status: str | None = None,
    type: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().get_campaigns(
            page, per_page, order_by, order, status, type
        )
    )


@mcp.tool(annotations=READ_ONLY)
async def get_campaign(campaign_id: int, no_body: bool | None = None) -> dict[str, Any]:
    return await _call(lambda: get_client().get_campaign(campaign_id, no_body))


@mcp.tool(annotations=MUTATING)
async def create_campaign(
    name: str,
    subject: str,
    lists: list[int],
    type: str = "regular",
    from_email: str | None = None,
    body: str | None = None,
    content_type: str = "richtext",
    altbody: str | None = None,
    template_id: int | None = None,
    tags: list[str] | None = None,
    send_later: bool | None = None,
    send_at: str | None = None,
    messenger: str | None = None,
    headers: list[dict[str, Any]] | None = None,
    auto_convert_plain_to_html: bool = True,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().create_campaign(
            name=name,
            subject=subject,
            lists=lists,
            type=type,
            from_email=from_email,
            body=body,
            content_type=content_type,
            altbody=altbody,
            template_id=template_id,
            tags=tags,
            send_later=send_later,
            send_at=send_at,
            messenger=messenger,
            headers=headers,
            auto_convert_plain_to_html=auto_convert_plain_to_html,
        )
    )


@mcp.tool(annotations=MUTATING)
async def update_campaign(
    campaign_id: int,
    name: str | None = None,
    subject: str | None = None,
    lists: list[int] | None = None,
    body: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().update_campaign(
            campaign_id,
            **compact_payload(
                {
                    "name": name,
                    "subject": subject,
                    "lists": lists,
                    "body": body,
                    "content_type": content_type,
                }
            ),
        )
    )


@mcp.tool(annotations=MUTATING)
async def send_campaign(campaign_id: int, confirm_send: bool = False) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send, "send campaign", campaign_id=campaign_id
    ):
        return blocked
    return await _call(lambda: get_client().send_campaign(campaign_id))


@mcp.tool(annotations=MUTATING)
async def test_campaign(
    campaign_id: int,
    subscribers: TestRecipientsPayload,
    confirm_send: bool = False,
) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send, "test campaign", campaign_id=campaign_id, subscribers=subscribers
    ):
        return blocked
    if blockers := _email_recipient_blockers(subscribers):
        return {
            "success": False,
            "sent": False,
            "campaign_id": campaign_id,
            "blockers": blockers,
        }
    return await _call(lambda: get_client().test_campaign(campaign_id, subscribers))


@mcp.tool(annotations=MUTATING)
async def safe_test_campaign(
    campaignId: int,
    testRecipients: TestRecipientsPayload,
    confirmSend: bool = False,
) -> dict[str, Any]:
    if not confirmSend:
        return (
            send_confirmation_required(
                False,
                "safe test campaign",
                campaignId=campaignId,
                testRecipientCount=len(testRecipients),
            )
            or {}
        )
    if blockers := _email_recipient_blockers(testRecipients):
        return {
            "success": False,
            "sent": False,
            "campaignId": campaignId,
            "blockers": blockers,
        }
    result = await get_client().test_campaign(campaignId, testRecipients)
    audit_id = write_safety_audit_log(
        "safe_test_campaign",
        "campaign",
        str(campaignId),
        "test_send",
        {"testRecipientCount": len(testRecipients)},
        {"sent": True},
    )
    return {
        "success": True,
        "sent": True,
        "campaignId": campaignId,
        "testRecipientCount": len(testRecipients),
        "auditId": audit_id,
        "data": result,
    }


@mcp.tool(annotations=MUTATING)
async def schedule_campaign(
    campaign_id: int, send_at: str, confirm_send: bool = False
) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send,
        "schedule campaign",
        campaign_id=campaign_id,
        send_at=send_at,
    ):
        return blocked
    return await _call(lambda: get_client().schedule_campaign(campaign_id, send_at))


@mcp.tool(annotations=MUTATING)
async def update_campaign_status(campaign_id: int, status: str) -> dict[str, Any]:
    return await _call(lambda: get_client().update_campaign_status(campaign_id, status))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_campaign(campaign_id: int, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete campaign", campaign_id=campaign_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_campaign(campaign_id))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_campaigns(
    campaign_ids: list[int], confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete campaigns", campaign_ids=campaign_ids
    ):
        return blocked
    return await _call(lambda: get_client().delete_campaigns(campaign_ids=campaign_ids))


@mcp.tool(annotations=READ_ONLY)
async def get_campaign_html_preview(campaign_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_campaign_preview(campaign_id))


@mcp.tool(annotations=READ_ONLY)
async def preview_campaign_body(
    campaign_id: int,
    body: str,
    content_type: str = "html",
    template_id: int | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().preview_campaign_body(
            campaign_id, body, content_type, template_id
        )
    )


@mcp.tool(annotations=READ_ONLY)
async def preview_campaign_text(
    campaign_id: int, body: str, content_type: str = "plain"
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().preview_campaign_text(campaign_id, body, content_type)
    )


@mcp.tool(annotations=READ_ONLY)
async def get_running_campaign_stats(campaign_ids: list[int]) -> dict[str, Any]:
    return await _call(lambda: get_client().get_running_campaign_stats(campaign_ids))


@mcp.tool(annotations=READ_ONLY)
async def get_campaign_analytics(
    campaign_id: int,
    type: str = "views",
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().get_campaign_analytics(
            campaign_id, type, from_date, to_date
        )
    )


@mcp.tool(annotations=MUTATING)
async def archive_campaign(campaign_id: int, archive: bool = True) -> dict[str, Any]:
    return await _call(lambda: get_client().archive_campaign(campaign_id, archive))


@mcp.tool(annotations=MUTATING)
async def convert_campaign_content(campaign_id: int, editor: str) -> dict[str, Any]:
    return await _call(
        lambda: get_client().convert_campaign_content(campaign_id, editor)
    )


@mcp.tool(annotations=READ_ONLY)
async def get_templates(no_body: bool | None = None) -> dict[str, Any]:
    return await _call(lambda: get_client().get_templates(no_body))


@mcp.tool(annotations=READ_ONLY)
async def get_template(template_id: int, no_body: bool | None = None) -> dict[str, Any]:
    return await _call(lambda: get_client().get_template(template_id, no_body))


@mcp.tool(annotations=MUTATING)
async def create_template(
    name: str,
    subject: str,
    body: str,
    type: str = "campaign",
    is_default: bool = False,
    body_source: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().create_template(
            name, subject, body, type, is_default, body_source
        )
    )


@mcp.tool(annotations=MUTATING)
async def update_template(
    template_id: int,
    name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    type: str | None = None,
    is_default: bool | None = None,
    body_source: str | None = None,
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().update_template(
            template_id,
            **compact_payload(
                {
                    "name": name,
                    "subject": subject,
                    "body": body,
                    "type": type,
                    "is_default": is_default,
                    "body_source": body_source,
                }
            ),
        )
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_template(template_id: int, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete template", template_id=template_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_template(template_id))


@mcp.tool(annotations=READ_ONLY)
async def preview_template(
    template_id: int, body: str, content_type: str = "html"
) -> dict[str, Any]:
    return await _call(
        lambda: get_client().preview_template(template_id, body, content_type)
    )


@mcp.tool(annotations=READ_ONLY)
async def get_template_html_preview(template_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_template_preview(template_id))


@mcp.tool(annotations=MUTATING)
async def set_default_template(template_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().set_default_template(template_id))


@mcp.tool(annotations=MUTATING)
async def send_transactional_email(
    template_id: int,
    subscriber_email: str | None = None,
    subscriber_id: int | None = None,
    subscriber_emails: list[str] | None = None,
    subscriber_ids: list[int] | None = None,
    subscriber_mode: str | None = None,
    from_email: str | None = None,
    subject: str | None = None,
    data: TransactionalDataPayload | None = None,
    headers: list[dict[str, Any]] | None = None,
    messenger: str | None = None,
    content_type: str = "html",
    altbody: str | None = None,
    confirm_send: bool = False,
) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send,
        "send transactional email",
        template_id=template_id,
        subscriber_email=subscriber_email,
        subscriber_emails=subscriber_emails,
    ):
        return blocked
    payload = compact_payload(
        {
            "template_id": template_id,
            "subscriber_email": subscriber_email,
            "subscriber_id": subscriber_id,
            "subscriber_emails": subscriber_emails,
            "subscriber_ids": subscriber_ids,
            "subscriber_mode": subscriber_mode,
            "from_email": from_email,
            "subject": subject,
            "data": data or {},
            "headers": headers,
            "messenger": messenger,
            "content_type": content_type,
            "altbody": altbody,
        }
    )
    return await _call(lambda: get_client().send_transactional_email(**payload))


@mcp.tool(annotations=READ_ONLY)
async def get_media_list() -> dict[str, Any]:
    return await _call(lambda: get_client().get_media())


@mcp.tool(annotations=READ_ONLY)
async def get_media_file(media_id: int) -> dict[str, Any]:
    return await _call(lambda: get_client().get_media_file(media_id))


@mcp.tool(annotations=MUTATING)
async def upload_media_file(file_path: str, title: str | None = None) -> dict[str, Any]:
    return await _call(lambda: get_client().upload_media(file_path, title))


@mcp.tool(annotations=MUTATING)
async def rename_media(media_id: int, new_title: str) -> dict[str, Any]:
    return await _call(lambda: get_client().update_media(media_id, new_title))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_media_file(media_id: int, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete media file", media_id=media_id
    ):
        return blocked
    return await _call(lambda: get_client().delete_media(media_id))


@mcp.tool(annotations=MUTATING)
async def replace_in_campaign_body(
    campaign_id: int, search: str, replace: str
) -> dict[str, Any]:
    campaign = await get_client().get_campaign(campaign_id)
    data = campaign.get("data", campaign)
    body = str(data.get("body") or "")
    data["body"] = body.replace(search, replace)
    return await _call(
        lambda: get_client().update_campaign(campaign_id, body=data["body"])
    )


@mcp.tool(annotations=MUTATING)
async def regex_replace_in_campaign_body(
    campaign_id: int, pattern: str, replace: str
) -> dict[str, Any]:
    campaign = await get_client().get_campaign(campaign_id)
    data = campaign.get("data", campaign)
    data["body"] = re.sub(pattern, replace, str(data.get("body") or ""))
    return await _call(
        lambda: get_client().update_campaign(campaign_id, body=data["body"])
    )


@mcp.tool(annotations=MUTATING)
async def batch_replace_in_campaign_body(
    campaign_id: int, replacements: CampaignBodyReplacementsPayload
) -> dict[str, Any]:
    campaign = await get_client().get_campaign(campaign_id)
    data = campaign.get("data", campaign)
    body = str(data.get("body") or "")
    for item in replacements:
        body = body.replace(item["search"], item["replace"])
    return await _call(lambda: get_client().update_campaign(campaign_id, body=body))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_gc_subscribers(type: str, confirm: bool = False) -> dict[str, Any]:
    if blocked := confirmation_required(confirm, "delete gc subscribers", type=type):
        return blocked
    return await _call(lambda: get_client().delete_gc_subscribers(type))


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_campaign_analytics(
    type: str, before_date: str, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete campaign analytics", type=type, before_date=before_date
    ):
        return blocked
    return await _call(
        lambda: get_client().delete_campaign_analytics(type, before_date)
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def delete_unconfirmed_subscriptions(
    before_date: str, confirm: bool = False
) -> dict[str, Any]:
    if blocked := confirmation_required(
        confirm, "delete unconfirmed subscriptions", before_date=before_date
    ):
        return blocked
    return await _call(
        lambda: get_client().delete_unconfirmed_subscriptions(before_date)
    )


@mcp.tool(annotations=MUTATING)
async def upsert_subscriber_profiles(
    profiles: SubscriberProfilesPayload, dryRun: bool = True
) -> dict[str, Any]:
    created = 0
    updated = 0
    planned_created = 0
    planned_updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for profile in profiles:
        email = str(profile.get("email") or "").strip()
        if not email:
            skipped += 1
            errors.append({"profile": profile, "error": "email is required"})
            continue
        try:
            existing = await _lookup_subscriber_by_email(email)
            incoming_attributes = profile.get("attributes", {})
            attributes = (
                dict(incoming_attributes)
                if isinstance(incoming_attributes, dict)
                else {}
            )
            if profile.get("externalId") is not None:
                attributes["externalId"] = profile["externalId"]
            if profile.get("source") is not None:
                attributes["source"] = profile["source"]
            incoming_tags = {
                str(tag) for tag in profile.get("tags", []) if str(tag).strip()
            }
            list_ids = [
                int(item)
                for item in profile.get("listIds", [])
                if isinstance(item, int)
            ]
            if existing is None:
                action = "create"
                final_attributes = attributes
                final_tags = sorted(incoming_tags)
                if not dryRun:
                    await get_client().create_subscriber(
                        email=email,
                        name=str(profile.get("name") or email),
                        status=str(profile.get("status") or "enabled"),
                        lists=list_ids,
                        attribs={**final_attributes, "tags": final_tags},
                    )
                    created += 1
                else:
                    planned_created += 1
            else:
                action = "update"
                existing_attributes = _subscriber_attribs(existing)
                existing_tags = set(_subscriber_tags(existing))
                final_tags = sorted(existing_tags | incoming_tags)
                final_attributes = {
                    **existing_attributes,
                    **attributes,
                    "tags": final_tags,
                }
                existing_list_ids = set(_list_ids_from_subscriber(existing))
                final_list_ids = sorted(existing_list_ids | set(list_ids))
                if not dryRun:
                    await get_client().update_subscriber(
                        subscriber_id=int(existing["id"]),
                        email=email,
                        name=profile.get("name") or existing.get("name"),
                        status=profile.get("status") or existing.get("status"),
                        lists=final_list_ids,
                        attribs=final_attributes,
                    )
                    updated += 1
                else:
                    planned_updated += 1
            details.append(
                {
                    "email": email,
                    "action": action,
                    "dryRun": dryRun,
                    "listIds": list_ids,
                    "attributeKeys": sorted(final_attributes),
                    "tags": final_tags,
                }
            )
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"email": email, "error": str(exc)})

    result = {
        "success": True,
        "dryRun": dryRun,
        "created": created,
        "updated": updated,
        "plannedCreated": planned_created,
        "plannedUpdated": planned_updated,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
    if not dryRun:
        audit_id = write_safety_audit_log(
            "upsert_subscriber_profiles",
            "subscriber_profile_batch",
            "batch",
            "bulk_upsert",
            {"profileCount": len(profiles)},
            {"created": created, "updated": updated, "skipped": skipped},
            [],
        )
        _append_json_log(
            _sync_log_path,
            {
                "auditId": audit_id,
                "toolName": "upsert_subscriber_profiles",
                "createdAt": _utc_now_iso(),
                "result": result,
            },
        )
        result["auditId"] = audit_id
    return result


@mcp.tool(annotations=READ_ONLY)
async def get_subscriber_context(
    subscriberId: int | None = None, email: str | None = None
) -> dict[str, Any]:
    if subscriberId is None and not email:
        return {
            "success": False,
            "error": {
                "error_type": "ValidationError",
                "message": "subscriberId or email is required",
            },
        }
    subscriber = await _lookup_subscriber(subscriberId, email)
    if subscriber is None:
        return {
            "success": False,
            "error": {"error_type": "NotFound", "message": "Subscriber not found"},
        }
    subscriber_id = int(subscriber.get("id", subscriberId or 0))
    bounces_response = await get_client().get_subscriber_bounces(subscriber_id)
    bounces = _results_from_response(bounces_response)
    warnings: list[str] = []
    if not _subscriber_attribs(subscriber):
        warnings.append("Subscriber has no attributes")
    if not _subscriber_lists(subscriber):
        warnings.append(
            "Subscriber is not associated with any lists in the returned payload"
        )
    return {
        "success": True,
        "subscriber": subscriber,
        "lists": _subscriber_lists(subscriber),
        "attributes": _subscriber_attribs(subscriber),
        "tags": _subscriber_tags(subscriber),
        "status": subscriber.get("status"),
        "bounceStatus": {"count": len(bounces), "items": bounces[:10]},
        "unsubscribeStatus": {"status": subscriber.get("status")},
        "recentCampaigns": [],
        "engagementSummary": {
            "sent": 0,
            "views": 0,
            "clicks": 0,
            "bounces": len(bounces),
            "unsubscribes": 1 if subscriber.get("status") == "unsubscribed" else 0,
        },
        "warnings": warnings,
    }


@mcp.tool(annotations=READ_ONLY)
async def audience_summary(
    listIds: list[int], filters: dict[str, Any] | None = None
) -> dict[str, Any]:
    del filters
    subscribers = await _collect_audience_subscribers(listIds)
    statuses = [str(item.get("status") or "").lower() for item in subscribers]
    coverage = _attribute_coverage(subscribers)
    warnings = [
        f"{field} has low coverage and should not be used as required personalization"
        for field, ratio in coverage.items()
        if ratio < 0.6
    ]
    tags = sorted(
        {tag for subscriber in subscribers for tag in _subscriber_tags(subscriber)}
    )
    return {
        "success": True,
        "estimatedCount": len(subscribers),
        "activeCount": sum(status in {"enabled", "confirmed"} for status in statuses),
        "disabledCount": statuses.count("disabled"),
        "blocklistedCount": statuses.count("blocklisted"),
        "bouncedCount": 0,
        "unsubscribedCount": statuses.count("unsubscribed"),
        "attributeCoverage": coverage,
        "tags": tags,
        "warnings": warnings,
    }


@mcp.tool(annotations=READ_ONLY)
async def personalization_fields_report(
    listIds: list[int], sampleSize: int = 500
) -> dict[str, Any]:
    subscribers = await _collect_audience_subscribers(listIds, sampleSize)
    coverage = _attribute_coverage(subscribers)
    examples: dict[str, Any] = {}
    for field in sorted(coverage):
        for subscriber in subscribers:
            value = _subscriber_field_value(subscriber, field)
            if value not in (None, ""):
                examples[field] = "<redacted>" if "email" in field.lower() else value
                break
    return {
        "success": True,
        "availableFields": sorted(coverage),
        "coverageByField": coverage,
        "recommendedSafeFields": [
            field for field, ratio in coverage.items() if ratio >= 0.75
        ],
        "riskyFields": [field for field, ratio in coverage.items() if ratio < 0.75],
        "examples": examples,
    }


@mcp.tool(annotations=READ_ONLY)
async def validate_message_personalization(
    subject: str,
    body: str,
    listIds: list[int],
    sampleSubscriberIds: list[int] | None = None,
) -> dict[str, Any]:
    subscribers = await _collect_audience_subscribers(listIds)
    if sampleSubscriberIds:
        sampled: list[dict[str, Any]] = []
        for subscriber_id in sampleSubscriberIds:
            subscriber = await _lookup_subscriber(subscriber_id=subscriber_id)
            if subscriber is not None:
                sampled.append(subscriber)
        subscribers = sampled or subscribers
    used = _extract_template_variables(subject, body)
    coverage = _attribute_coverage(subscribers, used)
    missing = [field for field in used if field not in coverage or coverage[field] == 0]
    low = [
        field
        for field in used
        if field not in missing and coverage.get(field, 0) < 0.75
    ]
    warnings = [
        f"{field} exists but has low coverage across the target audience"
        for field in low
    ]
    blockers = [
        f"{field} is used but missing from the target audience" for field in missing
    ]
    return {
        "success": True,
        "usedVariables": used,
        "missingVariables": missing,
        "lowCoverageVariables": low,
        "coverageByVariable": {field: coverage.get(field, 0.0) for field in used},
        "warnings": warnings,
        "blockers": blockers,
        "riskLevel": _risk_level(warnings, blockers),
    }


def _subscriber_field_value(subscriber: dict[str, Any], field: str) -> Any:
    if field == "name":
        return subscriber.get("name")
    if field == "email":
        return subscriber.get("email")
    return _subscriber_attribs(subscriber).get(field)


async def _campaign_risk_check_data(
    campaign_id: int,
    require_test_send: bool = True,
    max_audience_size: int = 5000,
) -> dict[str, Any]:
    campaign = _one_from_response(await get_client().get_campaign(campaign_id)) or {}
    warnings: list[str] = []
    blockers: list[str] = []
    recommendations: list[str] = []
    subject = str(campaign.get("subject") or "")
    body = str(campaign.get("body") or "")
    if not subject:
        blockers.append("Campaign subject is missing")
    if not body:
        blockers.append("Campaign body is missing")
    list_ids = _extract_campaign_list_ids(campaign)
    audience = await _collect_audience_subscribers(list_ids) if list_ids else []
    if not list_ids:
        blockers.append("Campaign has no target lists in the returned payload")
    if len(audience) == 0 and list_ids:
        blockers.append("Campaign audience appears to be empty")
    if len(audience) > max_audience_size:
        warnings.append("Audience is large compared to maxAudienceSize")
    status = str(campaign.get("status") or "").lower()
    if status in {"running", "sent", "finished"}:
        blockers.append(f"Campaign status is not sendable: {status}")
    personalization = await validate_message_personalization(subject, body, list_ids)
    blockers.extend(str(item) for item in personalization.get("blockers", []))
    warnings.extend(str(item) for item in personalization.get("warnings", []))
    if require_test_send:
        recommendations.append("Send a test email before sending the campaign")
    return {
        "success": True,
        "campaignId": campaign_id,
        "riskLevel": _risk_level(warnings, blockers),
        "warnings": warnings,
        "blockers": blockers,
        "recommendations": recommendations,
        "audience": {"estimatedCount": len(audience), "listIds": list_ids},
    }


@mcp.tool(annotations=READ_ONLY)
async def campaign_risk_check(
    campaignId: int, requireTestSend: bool = True, maxAudienceSize: int = 5000
) -> dict[str, Any]:
    return await _campaign_risk_check_data(campaignId, requireTestSend, maxAudienceSize)


@mcp.tool(annotations=MUTATING)
async def safe_send_campaign(
    campaignId: int,
    confirmSend: bool = False,
    approval: ApprovalPayload | None = None,
    requireTestSend: bool = True,
    testRecipients: list[str] | None = None,
) -> dict[str, Any]:
    if not confirmSend:
        return (
            send_confirmation_required(
                False, "safe send campaign", campaignId=campaignId
            )
            or {}
        )
    risk = await _campaign_risk_check_data(campaignId, requireTestSend)
    blockers = list(risk.get("blockers", []))
    if approval_blocker := _approval_blocker(approval):
        blockers.append(approval_blocker)
    if blockers:
        return {
            "success": False,
            "sent": False,
            "campaignId": campaignId,
            "riskCheck": risk,
            "blockers": blockers,
        }
    test_status = "not_required"
    if requireTestSend:
        if not testRecipients:
            return {
                "success": False,
                "sent": False,
                "campaignId": campaignId,
                "riskCheck": risk,
                "blockers": ["requireTestSend=true but testRecipients is empty"],
            }
        await get_client().test_campaign(campaignId, testRecipients)
        test_status = "sent"
    send_result = await get_client().send_campaign(campaignId)
    audit_id = write_safety_audit_log(
        "safe_send_campaign",
        "campaign",
        str(campaignId),
        "send",
        {
            "approval": approval,
            "requireTestSend": requireTestSend,
            "testRecipientCount": len(testRecipients or []),
        },
        {"sent": True},
        list(risk.get("warnings", [])),
    )
    return {
        "success": True,
        "sent": True,
        "campaignId": campaignId,
        "riskCheck": risk,
        "approvalStatus": (approval or {}).get("status", "not_required"),
        "testSendStatus": test_status,
        "auditId": audit_id,
        "warnings": risk.get("warnings", []),
        "data": send_result,
    }


@mcp.tool(annotations=MUTATING)
async def safe_send_transactional_email(
    templateId: int,
    recipientEmail: str | None = None,
    recipientSubscriberId: int | None = None,
    subject: str | None = None,
    data: TransactionalDataPayload | None = None,
    contentType: str = "html",
    confirmSend: bool = False,
    idempotencyKey: str | None = None,
) -> dict[str, Any]:
    if not confirmSend:
        return (
            send_confirmation_required(
                False, "safe send transactional email", templateId=templateId
            )
            or {}
        )
    if not recipientEmail and recipientSubscriberId is None:
        return {
            "success": False,
            "sent": False,
            "blockers": ["recipientEmail or recipientSubscriberId is required"],
        }
    keys = _read_json_file(_idempotency_keys_path, {})
    if idempotencyKey and isinstance(keys, dict) and idempotencyKey in keys:
        return {
            "success": True,
            "sent": False,
            "skipped": True,
            "reason": "idempotencyKey already processed",
            "idempotencyKey": idempotencyKey,
            "existing": keys[idempotencyKey],
        }
    template = _one_from_response(await get_client().get_template(templateId)) or {}
    warnings: list[str] = []
    if not template.get("body"):
        warnings.append("Template body is not available in Listmonk response")
    response = await get_client().send_transactional_email(
        template_id=templateId,
        subscriber_email=recipientEmail,
        subscriber_id=recipientSubscriberId,
        subject=subject,
        data=data or {},
        content_type=contentType,
    )
    audit_id = write_safety_audit_log(
        "safe_send_transactional_email",
        "template",
        str(templateId),
        "send_transactional",
        {
            "recipientEmail": recipientEmail,
            "recipientSubscriberId": recipientSubscriberId,
            "idempotencyKey": idempotencyKey,
        },
        {"sent": True},
        warnings,
    )
    if idempotencyKey:
        stored_keys = keys if isinstance(keys, dict) else {}
        stored_keys[idempotencyKey] = {"auditId": audit_id, "createdAt": _utc_now_iso()}
        _write_json_file(_idempotency_keys_path, stored_keys)
    data_response = _one_from_response(response) or response
    return {
        "success": True,
        "sent": True,
        "recipientEmail": recipientEmail,
        "messageId": data_response.get("id") or data_response.get("uuid"),
        "idempotencyKey": idempotencyKey,
        "auditId": audit_id,
        "warnings": warnings,
        "data": response,
    }


@mcp.tool(annotations=READ_ONLY)
async def campaign_performance_summary(
    campaignId: int, fromDate: str | None = None, toDate: str | None = None
) -> dict[str, Any]:
    campaign = _one_from_response(await get_client().get_campaign(campaignId)) or {}
    metrics: dict[str, Any] = {}
    unavailable: list[str] = []
    warnings: list[str] = []
    analytics_source = "analytics"
    analytics_not_found = False
    for metric in ("views", "clicks", "bounces", "unsubscribes"):
        try:
            metrics[metric] = _normalize_listmonk_response(
                await get_client().get_campaign_analytics(
                    campaignId, metric, fromDate, toDate
                )
            )
        except ListmonkAPIError as exc:
            unavailable.append(metric)
            if exc.status_code == 404:
                analytics_not_found = True
        except ResourceNotFoundError:
            unavailable.append(metric)
            analytics_not_found = True
        except Exception:  # noqa: BLE001
            unavailable.append(metric)
    if analytics_not_found:
        views = _int_field(campaign, "views")
        clicks = _int_field(campaign, "clicks")
        bounces = _int_field(campaign, "bounces")
        sent = _int_field(campaign, "sent")
        to_send = _int_field(campaign, "to_send")
        analytics_source = "campaign_fields"
        warnings.append(
            "Detailed analytics endpoint unavailable; using aggregate campaign fields."
        )
    else:
        views = (
            len(metrics.get("views", []))
            if isinstance(metrics.get("views"), list)
            else int(metrics.get("views", {}).get("total", 0))
            if isinstance(metrics.get("views"), dict)
            else 0
        )
        clicks = (
            len(metrics.get("clicks", []))
            if isinstance(metrics.get("clicks"), list)
            else int(metrics.get("clicks", {}).get("total", 0))
            if isinstance(metrics.get("clicks"), dict)
            else 0
        )
        bounces = (
            len(metrics.get("bounces", []))
            if isinstance(metrics.get("bounces"), list)
            else int(metrics.get("bounces", {}).get("total", 0))
            if isinstance(metrics.get("bounces"), dict)
            else 0
        )
        sent = _int_field(campaign, "sent")
        to_send = _int_field(campaign, "to_send")
    recommendations = []
    if clicks and views and clicks / max(views, 1) >= 0.1:
        recommendations.append("Click rate is strong compared to views")
    if unavailable:
        recommendations.append(
            "Some metrics are unavailable from the Listmonk API response"
        )
    unsubscribes = metrics.get("unsubscribes", 0)
    return {
        "success": True,
        "campaignId": campaignId,
        "campaignName": campaign.get("name"),
        "subject": campaign.get("subject"),
        "views": views,
        "clicks": clicks,
        "bounces": bounces,
        "sent": sent,
        "toSend": to_send,
        "unsubscribes": unsubscribes,
        "topLinks": [],
        "engagementRate": round(clicks / max(views, 1), 4),
        "recommendations": recommendations,
        "unavailableMetrics": unavailable,
        "analyticsSource": analytics_source,
        "warnings": warnings,
    }


def _mark_detailed_analytics_unavailable(
    event_type: str, unsupported: list[dict[str, str]], warnings: list[str]
) -> None:
    unsupported.append(
        {
            "eventType": event_type,
            "reason": "Detailed analytics endpoint unavailable; event-level data is not available for this campaign.",
        }
    )
    warning = (
        "Listmonk returned 404 for detailed analytics; use "
        "campaign_performance_summary for aggregate metrics."
    )
    if warning not in warnings:
        warnings.append(warning)


@mcp.tool(annotations=READ_ONLY)
async def export_engagement_events(
    campaignId: int,
    fromDate: str | None = None,
    toDate: str | None = None,
    eventTypes: list[str] | None = None,
) -> dict[str, Any]:
    requested = eventTypes or ["email_viewed", "email_clicked"]
    type_map = {"email_viewed": "views", "email_clicked": "clicks"}
    events: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    warnings: list[str] = []
    campaign = _one_from_response(await get_client().get_campaign(campaignId)) or {}
    for event_type in requested:
        metric = type_map.get(event_type)
        if metric is None:
            unsupported.append(
                {
                    "eventType": event_type,
                    "reason": "Listmonk API wrapper does not expose event-level data for this event type",
                }
            )
            continue
        try:
            analytics = _normalize_listmonk_response(
                await get_client().get_campaign_analytics(
                    campaignId, metric, fromDate, toDate
                )
            )
        except (ListmonkAPIError, ResourceNotFoundError) as exc:
            if isinstance(exc, ResourceNotFoundError) or exc.status_code == 404:
                _mark_detailed_analytics_unavailable(event_type, unsupported, warnings)
                continue
            raise
        if not isinstance(analytics, list):
            unsupported.append(
                {
                    "eventType": event_type,
                    "reason": "Listmonk API returned only aggregate analytics for this event type",
                }
            )
            continue
        for item in analytics:
            if isinstance(item, dict):
                events.append(
                    {
                        "eventType": event_type,
                        "eventId": str(item.get("id") or uuid4().hex),
                        "occurredAt": item.get("created_at") or item.get("timestamp"),
                        "subscriberId": item.get("subscriber_id"),
                        "email": item.get("email"),
                        "campaignId": campaignId,
                        "campaignName": campaign.get("name"),
                        "metadata": {
                            key: value
                            for key, value in item.items()
                            if key
                            not in {
                                "id",
                                "created_at",
                                "timestamp",
                                "subscriber_id",
                                "email",
                            }
                        },
                    }
                )
    return {
        "success": True,
        "supported": not unsupported,
        "events": events,
        "unsupported": unsupported,
        "warnings": warnings,
    }


@mcp.tool(annotations=READ_ONLY)
async def export_subscriber_communication_summary(
    subscriberId: int | None = None,
    email: str | None = None,
    fromDate: str | None = None,
    toDate: str | None = None,
) -> dict[str, Any]:
    context = await get_subscriber_context(subscriberId, email)
    if not context.get("success"):
        return cast(dict[str, Any], context)
    engagement = context["engagementSummary"]
    subscriber = context["subscriber"]
    summary = (
        f"Subscriber received {engagement['sent']} campaigns, opened {engagement['views']}, "
        f"clicked {engagement['clicks']} links, and had {engagement['bounces']} bounces."
    )
    markdown = (
        "## Communication Summary\n\n"
        f"- Subscriber: {subscriber.get('email')}\n"
        f"- Period: {fromDate or 'unspecified'} to {toDate or 'unspecified'}\n"
        f"- Summary: {summary}\n"
    )
    return {
        "success": True,
        "subscriber": subscriber,
        "summary": summary,
        "campaigns": [],
        "transactionalEmails": [],
        "engagement": engagement,
        "markdown": markdown,
    }


@mcp.tool(annotations=READ_ONLY)
async def export_campaign_markdown(
    campaignId: int, includeBody: bool = True, includeStats: bool = True
) -> dict[str, Any]:
    campaign = _one_from_response(await get_client().get_campaign(campaignId)) or {}
    title = f"Campaign - {campaign.get('name') or campaignId}"
    sections = [
        f"# {title}",
        "",
        f"- Campaign ID: {campaignId}",
        f"- Subject: {campaign.get('subject') or ''}",
    ]
    if includeBody:
        sections.extend(["", "## Body", "", str(campaign.get("body") or "")])
    stats = None
    if includeStats:
        stats = await campaign_performance_summary(campaignId)
        sections.extend(
            [
                "",
                "## Stats",
                "",
                f"- Views: {stats.get('views', 0)}",
                f"- Clicks: {stats.get('clicks', 0)}",
            ]
        )
    return {
        "success": True,
        "title": title,
        "markdown": "\n".join(sections),
        "metadata": {
            "campaignId": campaignId,
            "subject": campaign.get("subject"),
            "statsIncluded": includeStats,
            "bodyIncluded": includeBody,
        },
    }


@mcp.tool(annotations=READ_ONLY)
async def export_campaign_postmortem_markdown(
    campaignId: int, fromDate: str | None = None, toDate: str | None = None
) -> dict[str, Any]:
    summary = await campaign_performance_summary(campaignId, fromDate, toDate)
    title = f"Postmortem - {summary.get('campaignName') or campaignId}"
    markdown = (
        f"# {title}\n\n"
        f"- Campaign ID: {campaignId}\n"
        f"- Subject: {summary.get('subject') or ''}\n"
        f"- Views: {summary.get('views', 0)}\n"
        f"- Clicks: {summary.get('clicks', 0)}\n"
        f"- Engagement rate: {summary.get('engagementRate', 0)}\n"
    )
    unavailable = summary.get("unavailableMetrics", [])
    if unavailable:
        markdown += (
            f"\nMissing metrics: {', '.join(str(item) for item in unavailable)}\n"
        )
    return {
        "success": True,
        "title": title,
        "markdown": markdown,
        "recommendations": summary.get("recommendations", []),
        "metadata": {"campaignId": campaignId, "unavailableMetrics": unavailable},
    }


@mcp.tool(annotations=MUTATING)
async def safe_schedule_campaign(
    campaignId: int,
    sendAt: str,
    confirmSchedule: bool = False,
    approval: ApprovalPayload | None = None,
) -> dict[str, Any]:
    if not confirmSchedule:
        return {
            "success": False,
            "scheduled": False,
            "error": {
                "error_type": "ScheduleConfirmationRequired",
                "message": "Set confirmSchedule=true to schedule the campaign",
                "confirm_required": True,
            },
        }
    risk = await _campaign_risk_check_data(campaignId, require_test_send=False)
    blockers = list(risk.get("blockers", []))
    if approval_blocker := _approval_blocker(approval):
        blockers.append(approval_blocker)
    if blockers:
        return {
            "success": False,
            "scheduled": False,
            "campaignId": campaignId,
            "riskCheck": risk,
            "blockers": blockers,
        }
    result = await get_client().schedule_campaign(campaignId, sendAt)
    audit_id = write_safety_audit_log(
        "safe_schedule_campaign",
        "campaign",
        str(campaignId),
        "schedule",
        {"sendAt": sendAt, "approval": approval},
        {"scheduled": True},
        list(risk.get("warnings", [])),
    )
    return {
        "success": True,
        "scheduled": True,
        "campaignId": campaignId,
        "sendAt": sendAt,
        "riskCheck": risk,
        "approvalStatus": (approval or {}).get("status", "not_required"),
        "auditId": audit_id,
        "warnings": risk.get("warnings", []),
        "data": result,
    }


@mcp.resource("listmonk://subscriber/{subscriber_id}")
async def get_subscriber_by_id(subscriber_id: str) -> str:
    return json.dumps(await get_client().get_subscriber(int(subscriber_id)), indent=2)


@mcp.resource("listmonk://subscriber/email/{email}")
async def get_subscriber_by_email(email: str) -> str:
    return json.dumps(await get_client().get_subscriber_by_email(email), indent=2)


@mcp.resource("listmonk://subscribers")
async def list_subscribers() -> str:
    return json.dumps(await get_client().get_subscribers(), indent=2)


@mcp.resource("listmonk://campaigns")
async def list_campaigns() -> str:
    return json.dumps(await get_client().get_campaigns(), indent=2)


@mcp.resource("listmonk://campaign/{campaign_id}")
async def get_campaign_by_id(campaign_id: str) -> str:
    return json.dumps(await get_client().get_campaign(int(campaign_id)), indent=2)


@mcp.resource("listmonk://campaign/{campaign_id}/preview")
async def get_campaign_preview(campaign_id: str) -> str:
    return json.dumps(
        await get_client().get_campaign_preview(int(campaign_id)), indent=2
    )


@mcp.resource("listmonk://lists")
async def list_mailing_lists() -> str:
    return json.dumps(await get_client().get_lists(), indent=2)


@mcp.resource("listmonk://list/{list_id}")
async def get_list_by_id(list_id: str) -> str:
    return json.dumps(await get_client().get_list(int(list_id)), indent=2)


@mcp.resource("listmonk://list/{list_id}/subscribers")
async def get_list_subscribers_resource(list_id: str) -> str:
    return json.dumps(await get_client().get_list_subscribers(int(list_id)), indent=2)


@mcp.resource("listmonk://templates")
async def list_templates() -> str:
    return json.dumps(await get_client().get_templates(), indent=2)


@mcp.resource("listmonk://template/{template_id}")
async def get_template_by_id(template_id: str) -> str:
    return json.dumps(await get_client().get_template(int(template_id)), indent=2)


@mcp.resource("listmonk://template/{template_id}/preview")
async def get_template_preview(template_id: str) -> str:
    return json.dumps(
        await get_client().get_template_preview(int(template_id)), indent=2
    )


@mcp.resource("listmonk://media")
async def list_media_files() -> str:
    return json.dumps(await get_client().get_media(), indent=2)


def run() -> None:
    mcp.run()


def main() -> None:
    app = typer.Typer(add_completion=False)

    @app.callback(invoke_without_command=True)
    def _main(
        version_flag: bool = typer.Option(
            False, "--version", help="Show version and exit."
        ),
    ) -> None:
        if version_flag:
            try:
                pkg_version = version("listmonk-mcp-bridge")
            except PackageNotFoundError:
                pkg_version = "0.0.0"
            typer.echo(f"listmonk-mcp-bridge {pkg_version}")
            raise typer.Exit()
        run()

    app()


if __name__ == "__main__":
    main()
