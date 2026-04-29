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
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

import typer
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from .client import ListmonkClient, compact_payload
from .config import Config
from .config import get_config as load_runtime_config
from .exceptions import safe_execute_async

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
    response = await get_client().get_list_subscribers(list_id, page, per_page)
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
    campaign_id: int, subscribers: list[str], confirm_send: bool = False
) -> dict[str, Any]:
    if blocked := send_confirmation_required(
        confirm_send, "test campaign", campaign_id=campaign_id, subscribers=subscribers
    ):
        return blocked
    return await _call(lambda: get_client().test_campaign(campaign_id, subscribers))


@mcp.tool(annotations=MUTATING)
async def schedule_campaign(campaign_id: int, send_at: str) -> dict[str, Any]:
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
    data: dict[str, Any] | None = None,
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
