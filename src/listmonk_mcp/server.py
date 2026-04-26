"""Listmonk MCP Server using FastMCP framework."""

import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Annotated, Any

import typer
from mcp.server import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from .client import ListmonkAPIError, ListmonkClient, create_client
from .config import Config, load_config, validate_config
from .exceptions import safe_execute_async

# Global state
_client: ListmonkClient | None = None
_config: Config | None = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("listmonk_mcp.audit")
operations_logger = logging.getLogger("listmonk_mcp.operations")

_bulk_query_events: dict[str, deque[float]] = defaultdict(deque)


def _redact_audit_value(key: str, value: Any) -> Any:
    if any(secret in key.lower() for secret in ("password", "token", "secret")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _redact_audit_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_audit_value(key, item) for item in value]
    return value


def audit_confirmed_operation(kind: str, operation: str, **context: Any) -> None:
    """Emit a structured audit log for confirmed high-impact operations."""
    redacted_context = {
        key: _redact_audit_value(key, value)
        for key, value in context.items()
    }
    audit_logger.warning(
        "confirmed_operation %s",
        json.dumps(
            {
                "kind": kind,
                "operation": operation,
                "context": redacted_context,
            },
            sort_keys=True,
        ),
    )


def get_bulk_query_rate_limit_per_minute() -> int:
    """Get the per-process bulk query operation rate limit."""
    raw_limit = os.getenv("LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE", "30")
    try:
        return int(raw_limit)
    except ValueError:
        logger.warning("Invalid LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE=%r; using 30", raw_limit)
        return 30


def check_bulk_query_rate_limit(operation: str, query: str | None = None) -> dict[str, Any] | None:
    """Rate limit query-driven bulk operations within this server process."""
    limit = get_bulk_query_rate_limit_per_minute()
    if limit <= 0:
        operations_logger.info("bulk_query_rate_limit_disabled operation=%s", operation)
        return None

    now = time.monotonic()
    window_start = now - 60
    events = _bulk_query_events[operation]
    while events and events[0] < window_start:
        events.popleft()

    if len(events) >= limit:
        operations_logger.warning(
            "bulk_query_rate_limited operation=%s limit=%s query_present=%s",
            operation,
            limit,
            query is not None,
        )
        return {
            "success": False,
            "error": {
                "error_type": "RateLimitExceeded",
                "message": f"Bulk query operation rate limit exceeded for {operation}",
                "operation": operation,
                "limit_per_minute": limit,
                "retry_after_seconds": 60,
            },
        }

    events.append(now)
    operations_logger.info(
        "bulk_query_operation_allowed operation=%s remaining=%s query_present=%s",
        operation,
        max(limit - len(events), 0),
        query is not None,
    )
    return None


@asynccontextmanager
async def lifespan(app: Any) -> Any:
    """Server lifespan context manager."""
    global _client, _config

    try:
        # Load and validate configuration
        _config = load_config()
        validate_config()

        logger.info(f"Connecting to Listmonk at {_config.url}")

        # Create and connect client
        _client = await create_client(_config)

        logger.info("Listmonk MCP Server started successfully")
        yield

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise
    finally:
        # Cleanup
        if _client:
            await _client.close()
            logger.info("Listmonk client disconnected")


# Register tools directly on the production server. This avoids relying on
# FastMCP private internals to copy tools between server instances.
mcp = FastMCP("Listmonk MCP Server", lifespan=lifespan)

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
SIDE_EFFECT_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
DESTRUCTIVE_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
EMAIL_SEND_TOOL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


def confirmation_required(confirm: bool, operation: str, **context: Any) -> dict[str, Any] | None:
    """Require an explicit confirmation flag before side effects that destroy data."""
    if confirm:
        audit_confirmed_operation("confirmed", operation, **context)
        return None

    return {
        "success": False,
        "error": {
            "error_type": "ConfirmationRequired",
            "message": f"Set confirm=true to run operation requiring confirmation: {operation}",
            "operation": operation,
            "confirm_required": True,
            "context": context,
        },
    }


def send_confirmation_required(confirm_send: bool, operation: str, **context: Any) -> dict[str, Any] | None:
    """Require explicit confirmation before sending real email."""
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


SettingsPayload = Annotated[
    dict[str, Any],
    Field(description="Listmonk settings object to update"),
    WithJsonSchema(
        {
            "type": "object",
            "description": "Listmonk settings object to update",
            "properties": {
                "app": {"type": "object", "description": "Application settings"},
                "privacy": {"type": "object", "description": "Privacy settings"},
                "smtp": {"type": "object", "description": "SMTP settings"},
                "messengers": {"type": "object", "description": "Messenger settings"},
                "bounce": {"type": "object", "description": "Bounce processing settings"},
                "media": {"type": "object", "description": "Media upload settings"},
                "security": {"type": "object", "description": "Security settings"},
                "performance": {"type": "object", "description": "Performance settings"},
                "appearance": {"type": "object", "description": "Appearance settings"},
            },
            "additionalProperties": True,
        }
    ),
]

SmtpSettingsPayload = Annotated[
    dict[str, Any],
    Field(description="SMTP settings object to test"),
    WithJsonSchema(
        {
            "type": "object",
            "description": "SMTP settings object to test",
            "properties": {
                "enabled": {"type": "boolean"},
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "auth_protocol": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "hello_hostname": {"type": "string"},
                "max_conns": {"type": "integer"},
                "idle_timeout": {"type": "string"},
                "wait_timeout": {"type": "string"},
                "tls_type": {"type": "string"},
                "tls_skip_verify": {"type": "boolean"},
                "email_headers": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": True,
        }
    ),
]

ImportSubscriberParamsPayload = Annotated[
    dict[str, Any],
    Field(description="Listmonk subscriber import parameters"),
    WithJsonSchema(
        {
            "type": "object",
            "description": "Listmonk subscriber import parameters",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["subscribe", "blocklist"],
                    "description": "Import mode",
                },
                "delim": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1,
                    "description": "CSV delimiter",
                },
                "lists": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List IDs to subscribe imported subscribers to",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite existing subscriber records",
                },
                "subscription_status": {
                    "type": "string",
                    "enum": ["confirmed", "unconfirmed", "unsubscribed"],
                    "description": "Subscription status for imported subscribers",
                },
            },
            "required": ["mode", "delim"],
            "additionalProperties": True,
        }
    ),
]

CampaignBodyReplacementsPayload = Annotated[
    list[dict[str, str]],
    Field(description="Search-and-replace operations for a campaign body"),
    WithJsonSchema(
        {
            "type": "array",
            "description": "Search-and-replace operations for a campaign body",
            "items": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                },
                "required": ["search", "replace"],
                "additionalProperties": False,
            },
        }
    ),
]


def create_production_server() -> FastMCP:
    """Return the configured production MCP server."""
    return mcp


def success_response(message: str, **data: Any) -> dict[str, Any]:
    """Create a consistent successful MCP tool response."""
    return {"success": True, "message": message, **data}


def collection_response(
    resource: str,
    items: list[Any],
    *,
    total: int | None = None,
    page: int | None = None,
    per_page: int | None = None,
) -> dict[str, Any]:
    """Create a consistent successful collection response."""
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


def get_client() -> ListmonkClient:
    """Get the global Listmonk client."""
    if _client is None:
        raise RuntimeError("Listmonk client not initialized")
    return _client


def get_config() -> Config:
    """Get the global configuration."""
    if _config is None:
        raise RuntimeError("Configuration not loaded")
    return _config


# Health Check Tool
@mcp.tool(annotations=READ_ONLY_TOOL)
async def check_listmonk_health() -> dict[str, Any]:
    """Check if Listmonk server is healthy and accessible."""
    async def _check_health_logic() -> dict[str, Any]:
        client = get_client()
        health_data = await client.health_check()
        config = get_config()

        return success_response(
            "Listmonk server is healthy",
            url=config.url,
            health=health_data,
        )

    return await safe_execute_async(_check_health_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_server_config() -> dict[str, Any]:
    """Get general Listmonk server config."""
    async def _get_config_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_server_config()
        return success_response("Server config retrieved", config=result.get("data", result))

    return await safe_execute_async(_get_config_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_i18n_language(lang: str) -> dict[str, Any]:
    """
    Get a Listmonk language pack.

    Args:
        lang: Language code
    """
    async def _get_lang_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_i18n_language(lang)
        return success_response("Language pack retrieved", lang=lang, language=result.get("data", result))

    return await safe_execute_async(_get_lang_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_dashboard_charts() -> dict[str, Any]:
    """Get Listmonk dashboard chart data."""
    async def _get_dashboard_charts_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_dashboard_charts()
        return success_response("Dashboard charts retrieved", charts=result.get("data", result))

    return await safe_execute_async(_get_dashboard_charts_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_dashboard_counts() -> dict[str, Any]:
    """Get Listmonk dashboard count data."""
    async def _get_dashboard_counts_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_dashboard_counts()
        return success_response("Dashboard counts retrieved", counts=result.get("data", result))

    return await safe_execute_async(_get_dashboard_counts_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_settings() -> dict[str, Any]:
    """Get Listmonk settings."""
    async def _get_settings_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_settings()
        return success_response("Settings retrieved", settings=result.get("data", result))

    return await safe_execute_async(_get_settings_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def update_settings(settings: SettingsPayload, confirm: bool = False) -> dict[str, Any]:
    """
    Update Listmonk settings.

    Args:
        settings: Settings object matching the Listmonk API schema
        confirm: Must be true to update Listmonk settings
    """
    async def _update_settings_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "update settings", settings_keys=sorted(settings.keys())):
            return error
        client = get_client()
        result = await client.update_settings(settings)
        return success_response("Settings updated", result=result.get("data", result))

    return await safe_execute_async(_update_settings_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def test_smtp_settings(settings: SmtpSettingsPayload) -> dict[str, Any]:
    """
    Test SMTP settings.

    Args:
        settings: SMTP test settings matching the Listmonk API schema
    """
    async def _test_smtp_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.test_smtp_settings(settings)
        return success_response("SMTP settings tested", result=result.get("data", result))

    return await safe_execute_async(_test_smtp_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def reload_app(confirm: bool = False) -> dict[str, Any]:
    """Reload the Listmonk app."""
    async def _reload_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "reload app"):
            return error
        client = get_client()
        result = await client.reload_app()
        return success_response("Listmonk reload requested", result=result.get("data", result))

    return await safe_execute_async(_reload_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_logs() -> dict[str, Any]:
    """Get buffered Listmonk logs."""
    async def _get_logs_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_logs()
        logs = result.get("data", result)
        return collection_response("logs", logs if isinstance(logs, list) else [logs])

    return await safe_execute_async(_get_logs_logic)  # type: ignore[no-any-return]


# Subscriber Management Tools
@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_subscribers(
    page: int = 1,
    per_page: int | str = 20,
    order_by: str = "created_at",
    order: str = "desc",
    query: str | None = None,
    subscription_status: str | None = None,
    list_ids: list[int] | None = None
) -> dict[str, Any]:
    """
    Get subscribers with pagination and filtering.

    Args:
        page: Page number
        per_page: Results per page or "all"
        order_by: Sort field
        order: Sort order
        query: Optional SQL filter expression
        subscription_status: Optional subscription status filter
        list_ids: Optional list IDs to filter by
    """
    async def _get_subscribers_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_subscribers(
            page=page,
            per_page=per_page,
            order_by=order_by,
            order=order,
            query=query,
            subscription_status=subscription_status,
            list_ids=list_ids
        )
        data = result.get("data", {})
        subscribers = data.get("results", []) if isinstance(data, dict) else data
        return collection_response(
            "subscribers",
            subscribers,
            total=data.get("total") if isinstance(data, dict) else None,
            page=data.get("page") if isinstance(data, dict) else None,
            per_page=data.get("per_page") if isinstance(data, dict) and isinstance(data.get("per_page"), int) else None,
        )

    return await safe_execute_async(_get_subscribers_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_subscriber(subscriber_id: int) -> dict[str, Any]:
    """
    Get a subscriber by ID.

    Args:
        subscriber_id: Subscriber ID
    """
    async def _get_subscriber_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_subscriber(subscriber_id)
        return success_response("Subscriber retrieved", subscriber=result.get("data", result))

    return await safe_execute_async(_get_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def add_subscriber(
    email: str,
    name: str,
    lists: list[int],
    status: str = "enabled",
    attributes: dict[str, Any] | None = None,
    preconfirm: bool = False
) -> dict[str, Any]:
    """
    Add a new subscriber to Listmonk.

    Args:
        email: Subscriber email address
        name: Subscriber name
        lists: List of mailing list IDs to subscribe to
        status: Subscriber status (enabled, disabled, blocklisted)
        attributes: Custom subscriber attributes
        preconfirm: Whether to preconfirm subscriptions
    """
    async def _add_subscriber_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_subscriber(
            email=email,
            name=name,
            status=status,
            lists=lists,
            attribs=attributes or {},
            preconfirm_subscriptions=preconfirm
        )

        subscriber_data = result.get("data", {})
        subscriber_id = subscriber_data.get("id", "unknown")
        return success_response(
            "Subscriber added",
            subscriber_id=subscriber_id,
            subscriber=subscriber_data,
        )

    return await safe_execute_async(_add_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def update_subscriber(
    subscriber_id: int,
    email: str | None = None,
    name: str | None = None,
    status: str | None = None,
    lists: list[int] | None = None,
    attributes: dict[str, Any] | None = None,
    list_uuids: list[str] | None = None,
    preconfirm_subscriptions: bool | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Update an existing subscriber.

    Args:
        subscriber_id: ID of the subscriber to update
        email: New email address
        name: New name
        status: New status (enabled, disabled, blocklisted)
        lists: New list of mailing list IDs
        attributes: New custom attributes
        list_uuids: New public list UUID subscriptions
        preconfirm_subscriptions: Whether to preconfirm double opt-in subscriptions
        confirm: Must be true when blocklisting or replacing list memberships
    """
    async def _update_subscriber_logic() -> dict[str, Any]:
        if (status == "blocklisted" or lists is not None or list_uuids is not None) and (
            error := confirmation_required(
                confirm,
                "sensitive subscriber update",
                subscriber_id=subscriber_id,
                status=status,
                lists=lists,
                list_uuids=list_uuids,
            )
        ):
            return error
        client = get_client()
        result = await client.update_subscriber(
            subscriber_id=subscriber_id,
            email=email,
            name=name,
            status=status,
            lists=lists,
            attribs=attributes,
            list_uuids=list_uuids,
            preconfirm_subscriptions=preconfirm_subscriptions
        )

        return success_response(
            "Subscriber updated",
            subscriber_id=subscriber_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=EMAIL_SEND_TOOL)
async def send_subscriber_optin(subscriber_id: int, confirm_send: bool = False) -> dict[str, Any]:
    """
    Send an opt-in confirmation email to a subscriber.

    Args:
        subscriber_id: ID of the subscriber
        confirm_send: Must be true to send the opt-in email
    """
    async def _send_optin_logic() -> dict[str, Any]:
        if error := send_confirmation_required(confirm_send, "send subscriber opt-in", subscriber_id=subscriber_id):
            return error
        client = get_client()
        result = await client.send_subscriber_optin(subscriber_id)
        return success_response("Subscriber opt-in sent", subscriber_id=subscriber_id, result=result.get("data", result))

    return await safe_execute_async(_send_optin_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_subscriber_export(subscriber_id: int) -> dict[str, Any]:
    """
    Export all data for a subscriber.

    Args:
        subscriber_id: ID of the subscriber
    """
    async def _export_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_subscriber_export(subscriber_id)
        return success_response("Subscriber export retrieved", subscriber_id=subscriber_id, export=result.get("data", result))

    return await safe_execute_async(_export_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_subscriber_bounces(subscriber_id: int) -> dict[str, Any]:
    """
    Get bounce records for a subscriber.

    Args:
        subscriber_id: ID of the subscriber
    """
    async def _get_bounces_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_subscriber_bounces(subscriber_id)
        return success_response("Subscriber bounces retrieved", subscriber_id=subscriber_id, bounces=result.get("data", result))

    return await safe_execute_async(_get_bounces_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_subscriber_bounces(subscriber_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete bounce records for a subscriber.

    Args:
        subscriber_id: ID of the subscriber
        confirm: Must be true to delete bounce records
    """
    async def _delete_bounces_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete subscriber bounces", subscriber_id=subscriber_id):
            return error
        client = get_client()
        result = await client.delete_subscriber_bounces(subscriber_id)
        return success_response("Subscriber bounces deleted", subscriber_id=subscriber_id, result=result.get("data", result))

    return await safe_execute_async(_delete_bounces_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def blocklist_subscriber(subscriber_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Blocklist a subscriber.

    Args:
        subscriber_id: ID of the subscriber to blocklist
        confirm: Must be true to blocklist the subscriber
    """
    async def _blocklist_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "blocklist subscriber", subscriber_id=subscriber_id):
            return error
        client = get_client()
        result = await client.blocklist_subscriber(subscriber_id)
        return success_response("Subscriber blocklisted", subscriber_id=subscriber_id, result=result.get("data", result))

    return await safe_execute_async(_blocklist_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def manage_subscriber_lists(
    action: str,
    target_list_ids: list[int],
    subscriber_ids: list[int] | None = None,
    query: str | None = None,
    status: str | None = None,
    list_id: int | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Add, remove, or unsubscribe subscribers from lists.

    Args:
        action: List action (add, remove, unsubscribe)
        target_list_ids: List IDs to modify
        subscriber_ids: Subscriber IDs to modify
        query: Optional SQL expression for subscribers to modify
        status: Subscription status (confirmed, unconfirmed, unsubscribed)
        list_id: Optional list ID variant endpoint
        confirm: Must be true for remove or unsubscribe actions
    """
    async def _manage_lists_logic() -> dict[str, Any]:
        if action in {"remove", "unsubscribe"} and (
            error := confirmation_required(
                confirm,
                "manage subscriber list memberships",
                action=action,
                target_list_ids=target_list_ids,
                subscriber_ids=subscriber_ids,
                query=query,
                list_id=list_id,
            )
        ):
            return error
        if query is not None and (
            error := check_bulk_query_rate_limit("manage_subscriber_lists", query=query)
        ):
            return error
        client = get_client()
        result = await client.manage_subscriber_lists(
            action=action,
            target_list_ids=target_list_ids,
            ids=subscriber_ids,
            query=query,
            status=status,
            list_id=list_id
        )
        return success_response("Subscriber lists updated", result=result.get("data", result))

    return await safe_execute_async(_manage_lists_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def blocklist_subscribers(
    subscriber_ids: list[int] | None = None,
    query: str | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Blocklist multiple subscribers by IDs or query.

    Args:
        subscriber_ids: Subscriber IDs to blocklist
        query: SQL expression for subscribers to blocklist
        confirm: Must be true to blocklist subscribers
    """
    async def _blocklist_many_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "blocklist subscribers", subscriber_ids=subscriber_ids, query=query):
            return error
        if query is not None and (
            error := check_bulk_query_rate_limit("blocklist_subscribers", query=query)
        ):
            return error
        client = get_client()
        result = await client.blocklist_subscribers(ids=subscriber_ids, query=query)
        return success_response("Subscribers blocklisted", result=result.get("data", result))

    return await safe_execute_async(_blocklist_many_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_subscribers_by_query(query: str, confirm: bool = False) -> dict[str, Any]:
    """
    Delete subscribers matched by a SQL expression.

    Args:
        query: SQL expression matching subscribers to delete
        confirm: Must be true to delete matching subscribers
    """
    async def _delete_query_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete subscribers by query", query=query):
            return error
        if error := check_bulk_query_rate_limit("delete_subscribers_by_query", query=query):
            return error
        client = get_client()
        result = await client.delete_subscribers_by_query(query)
        return success_response("Subscribers deleted by query", result=result.get("data", result))

    return await safe_execute_async(_delete_query_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def blocklist_subscribers_by_query(query: str, confirm: bool = False) -> dict[str, Any]:
    """
    Blocklist subscribers matched by a SQL expression.

    Args:
        query: SQL expression matching subscribers to blocklist
        confirm: Must be true to blocklist matching subscribers
    """
    async def _blocklist_query_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "blocklist subscribers by query", query=query):
            return error
        if error := check_bulk_query_rate_limit("blocklist_subscribers_by_query", query=query):
            return error
        client = get_client()
        result = await client.blocklist_subscribers_by_query(query)
        return success_response("Subscribers blocklisted by query", result=result.get("data", result))

    return await safe_execute_async(_blocklist_query_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def manage_subscriber_lists_by_query(
    query: str,
    action: str,
    target_list_ids: list[int],
    status: str | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Add, remove, or unsubscribe query-matched subscribers from lists.

    Args:
        query: SQL expression matching subscribers
        action: List action (add, remove, unsubscribe)
        target_list_ids: List IDs to modify
        status: Subscription status
        confirm: Must be true for query-based remove or unsubscribe actions
    """
    async def _manage_query_lists_logic() -> dict[str, Any]:
        if action in {"remove", "unsubscribe"} and (
            error := confirmation_required(
                confirm,
                "manage subscriber list memberships by query",
                query=query,
                action=action,
                target_list_ids=target_list_ids,
            )
        ):
            return error
        if error := check_bulk_query_rate_limit("manage_subscriber_lists_by_query", query=query):
            return error
        client = get_client()
        result = await client.manage_subscriber_lists_by_query(
            query=query,
            action=action,
            target_list_ids=target_list_ids,
            status=status
        )
        return success_response("Subscriber lists updated by query", result=result.get("data", result))

    return await safe_execute_async(_manage_query_lists_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def remove_subscriber(subscriber_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Remove a subscriber from Listmonk.

    Args:
        subscriber_id: ID of the subscriber to remove
        confirm: Must be true to remove the subscriber
    """
    async def _remove_subscriber_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "remove subscriber", subscriber_id=subscriber_id):
            return error
        client = get_client()
        result = await client.delete_subscriber(subscriber_id)

        return success_response(
            "Subscriber removed",
            subscriber_id=subscriber_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_remove_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def remove_subscribers(subscriber_ids: list[int], confirm: bool = False) -> dict[str, Any]:
    """
    Remove multiple subscribers from Listmonk.

    Args:
        subscriber_ids: Subscriber IDs to remove
        confirm: Must be true to remove the subscribers
    """
    async def _remove_subscribers_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "remove subscribers", subscriber_ids=subscriber_ids):
            return error
        client = get_client()
        result = await client.delete_subscribers(subscriber_ids)
        return success_response("Subscribers removed", subscriber_ids=subscriber_ids, result=result.get("data", result))

    return await safe_execute_async(_remove_subscribers_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def change_subscriber_status(subscriber_id: int, status: str, confirm: bool = False) -> dict[str, Any]:
    """
    Change subscriber status.

    Args:
        subscriber_id: ID of the subscriber
        status: New status (enabled, disabled, blocklisted)
        confirm: Must be true when changing status to blocklisted
    """
    async def _change_status_logic() -> dict[str, Any]:
        if status == "blocklisted" and (
            error := confirmation_required(confirm, "change subscriber status to blocklisted", subscriber_id=subscriber_id)
        ):
            return error
        client = get_client()
        result = await client.set_subscriber_status(subscriber_id, status)

        return success_response(
            "Subscriber status changed",
            subscriber_id=subscriber_id,
            status=status,
            result=result.get("data", result),
        )

    return await safe_execute_async(_change_status_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_bounces(
    campaign_id: int | None = None,
    page: int = 1,
    per_page: int | str = 20,
    source: str | None = None,
    order_by: str | None = None,
    order: str | None = None
) -> dict[str, Any]:
    """
    Get bounce records.

    Args:
        campaign_id: Optional campaign ID filter
        page: Page number
        per_page: Results per page or "all"
        source: Optional bounce source filter
        order_by: Sort field (email, campaign_name, source, created_at)
        order: Sort order (asc, desc)
    """
    async def _get_bounces_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_bounces(
            campaign_id=campaign_id,
            page=page,
            per_page=per_page,
            source=source,
            order_by=order_by,
            order=order
        )
        data = result.get("data", {})
        bounces = data.get("results", []) if isinstance(data, dict) else data
        return collection_response(
            "bounces",
            bounces,
            total=data.get("total") if isinstance(data, dict) else None,
            page=data.get("page") if isinstance(data, dict) else None,
            per_page=data.get("per_page") if isinstance(data, dict) and isinstance(data.get("per_page"), int) else None,
        )

    return await safe_execute_async(_get_bounces_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_bounce(bounce_id: int) -> dict[str, Any]:
    """
    Get a bounce record by ID.

    Args:
        bounce_id: Bounce ID
    """
    async def _get_bounce_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_bounce(bounce_id)
        return success_response("Bounce retrieved", bounce=result.get("data", result))

    return await safe_execute_async(_get_bounce_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_bounce(bounce_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete a bounce record by ID.

    Args:
        bounce_id: Bounce ID
        confirm: Must be true to delete the bounce record
    """
    async def _delete_bounce_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete bounce", bounce_id=bounce_id):
            return error
        client = get_client()
        result = await client.delete_bounce(bounce_id)
        return success_response("Bounce deleted", bounce_id=bounce_id, result=result.get("data", result))

    return await safe_execute_async(_delete_bounce_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_bounces(
    bounce_ids: list[int] | None = None,
    all: bool = False,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Delete multiple bounce records.

    Args:
        bounce_ids: Bounce IDs to delete
        all: Delete all bounce records
        confirm: Must be true to delete bounce records
    """
    async def _delete_bounces_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete bounces", bounce_ids=bounce_ids, all=all):
            return error
        client = get_client()
        result = await client.delete_bounces(bounce_ids=bounce_ids, all=all)
        return success_response("Bounces deleted", result=result.get("data", result))

    return await safe_execute_async(_delete_bounces_logic)  # type: ignore[no-any-return]


# Subscriber Resources
@mcp.resource("listmonk://subscriber/{subscriber_id}")
async def get_subscriber_by_id(subscriber_id: str) -> str:
    """Get subscriber details by ID."""
    try:
        client = get_client()
        result = await client.get_subscriber(int(subscriber_id))

        subscriber = result.get("data", {})

        lists_items = "\n".join(f"- {lst.get('name')} (ID: {lst.get('id')})" for lst in subscriber.get('lists', []))
        attributes_items = "\n".join(f"- **{k}:** {v}" for k, v in subscriber.get('attribs', {}).items())

        return f"""# Subscriber Details

**ID:** {subscriber.get('id')}
**Email:** {subscriber.get('email')}
**Name:** {subscriber.get('name')}
**Status:** {subscriber.get('status')}
**Created:** {subscriber.get('created_at')}
**Updated:** {subscriber.get('updated_at')}

## Lists
{lists_items}

## Attributes
{attributes_items}
"""

    except ListmonkAPIError as e:
        return f"Error retrieving subscriber {subscriber_id}: {str(e)}"


@mcp.resource("listmonk://subscriber/email/{email}")
async def get_subscriber_by_email(email: str) -> str:
    """Get subscriber details by email address."""
    try:
        client = get_client()
        result = await client.get_subscriber_by_email(email)

        subscriber = result.get("data", {})

        lists_items = "\n".join(f"- {lst.get('name')} (ID: {lst.get('id')})" for lst in subscriber.get('lists', []))
        attributes_items = "\n".join(f"- **{k}:** {v}" for k, v in subscriber.get('attribs', {}).items())

        return f"""# Subscriber Details

**ID:** {subscriber.get('id')}
**Email:** {subscriber.get('email')}
**Name:** {subscriber.get('name')}
**Status:** {subscriber.get('status')}
**Created:** {subscriber.get('created_at')}
**Updated:** {subscriber.get('updated_at')}

## Lists
{lists_items}

## Attributes
{attributes_items}
"""

    except ListmonkAPIError as e:
        return f"Error retrieving subscriber {email}: {str(e)}"


@mcp.resource("listmonk://subscribers")
async def list_subscribers() -> str:
    """List all subscribers with basic information."""
    try:
        client = get_client()
        result = await client.get_subscribers(per_page=50)

        data = result.get("data", {})
        subscribers = data.get("results", [])
        total = data.get("total", 0)

        subscriber_list = []
        for sub in subscribers:
            lists_str = ", ".join(lst.get('name', '') for lst in sub.get('lists', []))
            subscriber_list.append(
                f"- **{sub.get('name')}** ({sub.get('email')}) - Status: {sub.get('status')} - Lists: {lists_str}"
            )

        subscriber_items = "\n".join(subscriber_list)

        return f"""# Subscribers List

**Total Subscribers:** {total}
**Showing:** {len(subscribers)} subscribers

{subscriber_items}

*Use the get_subscriber_by_id or get_subscriber_by_email resources for detailed information.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving subscribers: {str(e)}"


# List Management Tools
@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_mailing_lists(
    query: str | None = None,
    status: str | None = None,
    minimal: bool | None = None,
    tags: list[str] | None = None,
    order_by: str | None = None,
    order: str | None = None,
    page: int = 1,
    per_page: int | str = 20
) -> dict[str, Any]:
    """
    Get all mailing lists.

    Returns mailing lists with optional Swagger query filters.
    """
    async def _get_lists_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_lists(
            query=query,
            status=status,
            minimal=minimal,
            tags=tags,
            order_by=order_by,
            order=order,
            page=page,
            per_page=per_page
        )

        data = result.get("data", {})
        lists = data.get("results", []) if isinstance(data, dict) else data

        return collection_response(
            "mailing_lists",
            lists,
            total=data.get("total") if isinstance(data, dict) else None,
            page=data.get("page") if isinstance(data, dict) else None,
            per_page=data.get("per_page") if isinstance(data, dict) and isinstance(data.get("per_page"), int) else None,
        )

    return await safe_execute_async(_get_lists_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_public_mailing_lists() -> dict[str, Any]:
    """Get public mailing lists exposed by Listmonk for subscription forms."""
    async def _get_public_lists_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_public_lists()
        data = result.get("data", result)
        return collection_response("public_lists", data if isinstance(data, list) else [data])

    return await safe_execute_async(_get_public_lists_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_mailing_list(list_id: int) -> dict[str, Any]:
    """
    Get a mailing list by ID.

    Args:
        list_id: Mailing list ID
    """
    async def _get_list_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_list(list_id)
        return success_response("Mailing list retrieved", list=result.get("data", result))

    return await safe_execute_async(_get_list_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def create_public_subscription(
    name: str,
    email: str,
    list_uuids: list[str]
) -> dict[str, Any]:
    """
    Create a subscription using Listmonk's public subscription endpoint.

    Args:
        name: Subscriber name
        email: Subscriber email address
        list_uuids: Public list UUIDs
    """
    async def _public_subscription_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_public_subscription(
            name=name,
            email=email,
            list_uuids=list_uuids
        )
        return success_response("Public subscription created", subscription=result.get("data", result))

    return await safe_execute_async(_public_subscription_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def create_mailing_list(
    name: str,
    type: str = "public",
    optin: str = "single",
    tags: list[str] | None = None,
    description: str | None = None
) -> dict[str, Any]:
    """
    Create a new mailing list.

    Args:
        name: List name
        type: List type (public, private)
        optin: Opt-in type (single, double)
        tags: List tags
        description: List description
    """
    async def _create_list_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_list(
            name=name,
            type=type,
            optin=optin,
            tags=tags or [],
            description=description
        )

        list_data = result.get("data", {})
        list_id = list_data.get("id", "unknown")
        return success_response(
            "Mailing list created",
            list_id=list_id,
            list=list_data,
        )

    return await safe_execute_async(_create_list_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def update_mailing_list(
    list_id: int,
    name: str | None = None,
    type: str | None = None,
    optin: str | None = None,
    tags: list[str] | None = None,
    description: str | None = None
) -> dict[str, Any]:
    """
    Update an existing mailing list.

    Args:
        list_id: ID of the list to update
        name: New list name
        type: New list type (public, private)
        optin: New opt-in type (single, double)
        tags: New list tags
        description: New list description
    """
    async def _update_list_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_list(
            list_id=list_id,
            name=name,
            type=type,
            optin=optin,
            tags=tags,
            description=description
        )

        return success_response(
            "Mailing list updated",
            list_id=list_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_list_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_mailing_list(list_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete a mailing list.

    Args:
        list_id: ID of the list to delete
        confirm: Must be true to delete the mailing list
    """
    async def _delete_list_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete mailing list", list_id=list_id):
            return error
        client = get_client()
        result = await client.delete_list(list_id)

        return success_response(
            "Mailing list deleted",
            list_id=list_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_delete_list_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_mailing_lists(
    list_ids: list[int] | None = None,
    query: str | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Delete multiple mailing lists by IDs or query.

    Args:
        list_ids: List IDs to delete
        query: Optional list search query to delete
        confirm: Must be true to delete mailing lists
    """
    async def _delete_lists_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete mailing lists", list_ids=list_ids, query=query):
            return error
        if query is not None and (
            error := check_bulk_query_rate_limit("delete_mailing_lists", query=query)
        ):
            return error
        client = get_client()
        result = await client.delete_lists(ids=list_ids, query=query)
        return success_response("Mailing lists deleted", result=result.get("data", result))

    return await safe_execute_async(_delete_lists_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_import_subscribers() -> dict[str, Any]:
    """Get subscriber import status."""
    async def _get_import_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_import_subscribers()
        return success_response("Import status retrieved", import_status=result.get("data", result))

    return await safe_execute_async(_get_import_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_import_subscriber_logs() -> dict[str, Any]:
    """Get subscriber import logs."""
    async def _get_import_logs_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_import_subscriber_logs()
        return success_response("Import logs retrieved", logs=result.get("data", result))

    return await safe_execute_async(_get_import_logs_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def import_subscribers(
    file_path: str,
    params: ImportSubscriberParamsPayload
) -> dict[str, Any]:
    """
    Upload a subscriber import file.

    Args:
        file_path: Absolute path to CSV/ZIP file to import
        params: Import parameters matching Listmonk's import API schema
    """
    async def _import_subscribers_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.import_subscribers(file_path=file_path, params=params)
        return success_response("Subscriber import uploaded", import_result=result.get("data", result))

    return await safe_execute_async(_import_subscribers_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def stop_import_subscribers(confirm: bool = False) -> dict[str, Any]:
    """Stop and remove a subscriber import."""
    async def _stop_import_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "stop and remove subscriber import"):
            return error
        client = get_client()
        result = await client.stop_import_subscribers()
        return success_response("Import stopped", result=result.get("data", result))

    return await safe_execute_async(_stop_import_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_list_subscribers_tool(
    list_id: int,
    page: int = 1,
    per_page: int = 20
) -> dict[str, Any]:
    """
    Get subscribers for a specific mailing list.

    Args:
        list_id: ID of the mailing list
        page: Page number for pagination
        per_page: Number of subscribers per page
    """
    async def _get_list_subscribers_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_list_subscribers(
            list_id=list_id,
            page=page,
            per_page=per_page
        )

        data = result.get("data", {})
        subscribers = data.get("results", []) if isinstance(data, dict) else data
        total = data.get("total", 0) if isinstance(data, dict) else len(subscribers)
        return {
            "success": True,
            "list_id": list_id,
            "page": page,
            "per_page": per_page,
            "count": len(subscribers),
            "total": total,
            "subscribers": subscribers,
        }

    return await safe_execute_async(_get_list_subscribers_logic)  # type: ignore[no-any-return]


# Campaign Management Tools
@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_campaigns(
    status: str | None = None,
    query: str | None = None,
    tags: list[str] | None = None,
    order_by: str | None = None,
    order: str | None = None,
    no_body: bool | None = None,
    page: int = 1,
    per_page: int | str = 20
) -> dict[str, Any]:
    """
    Get all campaigns with optional status filter.

    Args:
        status: Filter by status (draft, running, paused, finished, cancelled)
        query: Search query for campaign name and subject
        tags: Tags to filter campaigns
        order_by: Sort field (name, status, created_at, updated_at)
        order: Sort order (ASC, DESC)
        no_body: Return campaigns without body content
        page: Page number for pagination
        per_page: Number of campaigns per page
    """
    async def _get_campaigns_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaigns(
            page=page,
            per_page=per_page,
            status=status,
            query=query,
            tags=tags,
            order_by=order_by,
            order=order,
            no_body=no_body
        )

        data = result.get("data", {})
        campaigns = data.get("results", []) if isinstance(data, dict) else data
        total = data.get("total", 0) if isinstance(data, dict) else len(campaigns)

        return collection_response(
            "campaigns",
            campaigns,
            total=total,
            page=page,
            per_page=per_page if isinstance(per_page, int) else None,
        )

    return await safe_execute_async(_get_campaigns_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_campaign(campaign_id: int, no_body: bool | None = None) -> dict[str, Any]:
    """
    Get a specific campaign by ID including its full body content.

    Args:
        campaign_id: ID of the campaign to retrieve
        no_body: Return campaign without body content
    """
    async def _get_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaign(campaign_id, no_body=no_body)

        campaign = result.get("data", {})
        return success_response("Campaign retrieved", campaign=campaign)

    return await safe_execute_async(_get_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def create_campaign(
    name: str,
    subject: str,
    lists: list[int],
    type: str = "regular",
    content_type: str = "richtext",
    body: str | None = None,
    altbody: str | None = None,
    from_email: str | None = None,
    messenger: str | None = None,
    template_id: int | None = None,
    tags: list[str] | None = None,
    send_later: bool | None = None,
    send_at: str | None = None,
    headers: list[dict[str, Any]] | None = None,
    auto_convert_plain_to_html: bool = True
) -> dict[str, Any]:
    """
    Create a new email campaign.

    Args:
        name: Campaign name
        subject: Email subject line
        lists: List of mailing list IDs to send to
        type: Campaign type (regular, optin)
        content_type: Content type (richtext, html, markdown, plain)
        body: Campaign content body
        altbody: Plain text alternative body
        from_email: Optional sender email
        messenger: Messenger backend
        template_id: Template ID to use (optional)
        tags: Campaign tags
        send_later: Whether to schedule instead of draft
        send_at: Scheduled send time
        headers: Custom email headers
        auto_convert_plain_to_html: Convert plain text bodies to escaped HTML paragraphs by default.
            Set false to send plain content unchanged.
    """
    async def _create_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_campaign(
            name=name,
            subject=subject,
            lists=lists,
            type=type,
            content_type=content_type,
            body=body,
            altbody=altbody,
            from_email=from_email,
            messenger=messenger,
            template_id=template_id,
            tags=tags or [],
            send_later=send_later,
            send_at=send_at,
            headers=headers,
            auto_convert_plain_to_html=auto_convert_plain_to_html
        )

        campaign_data = result.get("data", {})
        campaign_id = campaign_data.get("id", "unknown")
        return success_response(
            "Campaign created",
            campaign_id=campaign_id,
            campaign=campaign_data,
        )

    return await safe_execute_async(_create_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def update_campaign(
    campaign_id: int,
    name: str | None = None,
    subject: str | None = None,
    lists: list[int] | None = None,
    body: str | None = None,
    altbody: str | None = None,
    from_email: str | None = None,
    content_type: str | None = None,
    messenger: str | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    template_id: int | None = None,
    send_later: bool | None = None,
    send_at: str | None = None,
    headers: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """
    Update an existing campaign.

    Args:
        campaign_id: ID of the campaign to update
        name: New campaign name
        subject: New email subject
        lists: New list of mailing list IDs
        body: New campaign content
        altbody: New plain text alternative body
        from_email: New sender email
        content_type: New content type
        messenger: New messenger backend
        type: New campaign type
        tags: New campaign tags
        template_id: New template ID
        send_later: Whether to schedule instead of draft
        send_at: Scheduled send time
        headers: Custom email headers
    """
    async def _update_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_campaign(
            campaign_id=campaign_id,
            name=name,
            subject=subject,
            lists=lists,
            body=body,
            altbody=altbody,
            from_email=from_email,
            content_type=content_type,
            messenger=messenger,
            type=type,
            tags=tags,
            template_id=template_id,
            send_later=send_later,
            send_at=send_at,
            headers=headers
        )

        return success_response(
            "Campaign updated",
            campaign_id=campaign_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=EMAIL_SEND_TOOL)
async def send_campaign(campaign_id: int, confirm_send: bool = False) -> dict[str, Any]:
    """
    Send a campaign immediately.

    Args:
        campaign_id: ID of the campaign to send
        confirm_send: Must be true to send the campaign
    """
    async def _send_campaign_logic() -> dict[str, Any]:
        if error := send_confirmation_required(confirm_send, "send campaign", campaign_id=campaign_id):
            return error
        client = get_client()
        result = await client.send_campaign(campaign_id)

        return success_response(
            "Campaign sent",
            campaign_id=campaign_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_send_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def schedule_campaign(campaign_id: int, send_at: str) -> dict[str, Any]:
    """
    Schedule a campaign for future delivery.

    Args:
        campaign_id: ID of the campaign to schedule
        send_at: ISO datetime string for when to send (e.g., '2024-12-25T10:00:00Z')
    """
    async def _schedule_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.schedule_campaign(campaign_id, send_at)

        return success_response(
            "Campaign scheduled",
            campaign_id=campaign_id,
            send_at=send_at,
            result=result.get("data", result),
        )

    return await safe_execute_async(_schedule_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def update_campaign_status(campaign_id: int, status: str) -> dict[str, Any]:
    """
    Update a campaign status.

    Args:
        campaign_id: ID of the campaign
        status: New status (scheduled, running, paused, cancelled)
    """
    async def _update_status_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_campaign_status(campaign_id, status)
        return success_response("Campaign status updated", campaign_id=campaign_id, status=status, result=result.get("data", result))

    return await safe_execute_async(_update_status_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_campaign(campaign_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete a campaign.

    Args:
        campaign_id: ID of the campaign to delete
        confirm: Must be true to delete the campaign
    """
    async def _delete_campaign_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete campaign", campaign_id=campaign_id):
            return error
        client = get_client()
        result = await client.delete_campaign(campaign_id)
        return success_response("Campaign deleted", campaign_id=campaign_id, result=result.get("data", result))

    return await safe_execute_async(_delete_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_campaigns(
    campaign_ids: list[int] | None = None,
    query: str | None = None,
    confirm: bool = False
) -> dict[str, Any]:
    """
    Delete multiple campaigns by IDs or query.

    Args:
        campaign_ids: Campaign IDs to delete
        query: Optional campaign query to delete
        confirm: Must be true to delete campaigns
    """
    async def _delete_campaigns_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete campaigns", campaign_ids=campaign_ids, query=query):
            return error
        if query is not None and (
            error := check_bulk_query_rate_limit("delete_campaigns", query=query)
        ):
            return error
        client = get_client()
        result = await client.delete_campaigns(ids=campaign_ids, query=query)
        return success_response("Campaigns deleted", result=result.get("data", result))

    return await safe_execute_async(_delete_campaigns_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_campaign_html_preview(campaign_id: int) -> dict[str, Any]:
    """
    Get a campaign HTML preview.

    Args:
        campaign_id: ID of the campaign
    """
    async def _get_campaign_preview_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaign_preview(campaign_id)
        return success_response("Campaign preview retrieved", preview=result.get("text", result.get("data", result)))

    return await safe_execute_async(_get_campaign_preview_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def preview_campaign_body(
    campaign_id: int,
    body: str,
    content_type: str,
    template_id: int | None = None
) -> dict[str, Any]:
    """
    Render a campaign HTML preview from body content.

    Args:
        campaign_id: ID of the campaign
        body: Campaign body
        content_type: Body content type
        template_id: Optional template ID
    """
    async def _preview_campaign_body_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.preview_campaign_body(
            campaign_id=campaign_id,
            body=body,
            content_type=content_type,
            template_id=template_id
        )
        return success_response("Campaign body preview rendered", preview=result.get("text", result.get("data", result)))

    return await safe_execute_async(_preview_campaign_body_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def preview_campaign_text(
    campaign_id: int,
    body: str,
    content_type: str,
    template_id: int | None = None
) -> dict[str, Any]:
    """
    Render a campaign text preview from body content.

    Args:
        campaign_id: ID of the campaign
        body: Campaign body
        content_type: Body content type
        template_id: Optional template ID
    """
    async def _preview_campaign_text_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.preview_campaign_text(
            campaign_id=campaign_id,
            body=body,
            content_type=content_type,
            template_id=template_id
        )
        return success_response("Campaign text preview rendered", preview=result.get("text", result.get("data", result)))

    return await safe_execute_async(_preview_campaign_text_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_running_campaign_stats(campaign_ids: list[int]) -> dict[str, Any]:
    """
    Get running stats for campaign IDs.

    Args:
        campaign_ids: Campaign IDs to inspect
    """
    async def _running_stats_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_running_campaign_stats(campaign_ids)
        return success_response("Running campaign stats retrieved", stats=result.get("data", result))

    return await safe_execute_async(_running_stats_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_campaign_analytics(
    analytics_type: str,
    campaign_ids: list[int],
    from_date: str,
    to_date: str
) -> dict[str, Any]:
    """
    Get campaign analytics counts.

    Args:
        analytics_type: Analytics type (links, views, clicks, bounces)
        campaign_ids: Campaign IDs to inspect
        from_date: Start date
        to_date: End date
    """
    async def _analytics_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaign_analytics(
            type=analytics_type,
            campaign_ids=campaign_ids,
            from_date=from_date,
            to_date=to_date
        )
        return success_response("Campaign analytics retrieved", analytics=result.get("data", result))

    return await safe_execute_async(_analytics_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def archive_campaign(
    campaign_id: int,
    archive: bool = True,
    archive_template_id: int | None = None,
    archive_meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Publish or unpublish a campaign in the public archive.

    Args:
        campaign_id: ID of the campaign
        archive: Whether the campaign should be archived
        archive_template_id: Archive template ID
        archive_meta: Archive metadata
    """
    async def _archive_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.archive_campaign(
            campaign_id=campaign_id,
            archive=archive,
            archive_template_id=archive_template_id,
            archive_meta=archive_meta
        )
        return success_response("Campaign archive updated", campaign_id=campaign_id, result=result.get("data", result))

    return await safe_execute_async(_archive_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def convert_campaign_content(
    campaign_id: int,
    body: str,
    content_type: str,
    template_id: int | None = None
) -> dict[str, Any]:
    """
    Convert campaign body content with Listmonk's content conversion endpoint.

    Args:
        campaign_id: ID of the campaign
        body: Campaign body content
        content_type: Source content type
        template_id: Optional template ID
    """
    async def _convert_content_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.convert_campaign_content(
            campaign_id=campaign_id,
            body=body,
            content_type=content_type,
            template_id=template_id
        )
        return success_response("Campaign content converted", content=result.get("data", result))

    return await safe_execute_async(_convert_content_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=EMAIL_SEND_TOOL)
async def test_campaign(
    campaign_id: int,
    subscribers: list[str],
    template_id: int | None = None,
    confirm_send: bool = False
) -> dict[str, Any]:
    """
    Send a campaign test message to arbitrary subscriber emails.

    Args:
        campaign_id: ID of the campaign
        subscribers: Subscriber email addresses
        template_id: Optional template ID
        confirm_send: Must be true to send the campaign test email
    """
    async def _test_campaign_logic() -> dict[str, Any]:
        if error := send_confirmation_required(
            confirm_send,
            "send campaign test",
            campaign_id=campaign_id,
            subscribers=subscribers,
        ):
            return error
        client = get_client()
        result = await client.test_campaign(
            campaign_id=campaign_id,
            subscribers=subscribers,
            template_id=template_id
        )
        return success_response("Campaign test sent", campaign_id=campaign_id, result=result.get("data", result))

    return await safe_execute_async(_test_campaign_logic)  # type: ignore[no-any-return]


# Campaign Resources
@mcp.resource("listmonk://campaigns")
async def list_campaigns() -> str:
    """List all campaigns with basic information."""
    try:
        client = get_client()
        result = await client.get_campaigns(per_page=50)

        data = result.get("data", {})
        campaigns = data.get("results", [])
        total = data.get("total", 0)

        campaign_list = []
        for camp in campaigns:
            lists_str = ", ".join(lst.get('name', '') for lst in camp.get('lists', []))
            status = camp.get('status', 'unknown')
            sent = camp.get('sent', 0)
            to_send = camp.get('to_send', 0)

            campaign_list.append(
                f"- **{camp.get('name')}** - Status: {status} - Sent: {sent}/{to_send} - Lists: {lists_str}"
            )

        campaign_items = "\n".join(campaign_list)

        return f"""# Campaigns List

**Total Campaigns:** {total}
**Showing:** {len(campaigns)} campaigns

{campaign_items}

*Use the get_campaign_by_id resource for detailed information.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving campaigns: {str(e)}"


@mcp.resource("listmonk://campaign/{campaign_id}")
async def get_campaign_by_id(campaign_id: str) -> str:
    """Get campaign details by ID."""
    try:
        client = get_client()
        result = await client.get_campaign(int(campaign_id))

        campaign = result.get("data", {})

        # Format lists
        lists_info = []
        for lst in campaign.get('lists', []):
            lists_info.append(f"- {lst.get('name')} (ID: {lst.get('id')})")

        # Format tags
        tags = campaign.get('tags', [])
        tags_str = ", ".join(tags) if tags else "None"

        lists_items = "\n".join(lists_info) if lists_info else "No lists assigned"

        return f"""# Campaign Details

**ID:** {campaign.get('id')}
**Name:** {campaign.get('name')}
**Subject:** {campaign.get('subject')}
**Status:** {campaign.get('status')}
**Type:** {campaign.get('type', 'regular')}
**Content Type:** {campaign.get('content_type', 'richtext')}

## Statistics
**To Send:** {campaign.get('to_send', 0)}
**Sent:** {campaign.get('sent', 0)}
**Views:** {campaign.get('views', 0)}
**Clicks:** {campaign.get('clicks', 0)}

## Timing
**Created:** {campaign.get('created_at')}
**Updated:** {campaign.get('updated_at')}
**Started:** {campaign.get('started_at', 'Not started')}

## Lists
{lists_items}

## Tags
{tags_str}

## Template
**Template ID:** {campaign.get('template_id', 'None')}
"""

    except ListmonkAPIError as e:
        return f"Error retrieving campaign {campaign_id}: {str(e)}"


@mcp.resource("listmonk://campaign/{campaign_id}/preview")
async def get_campaign_preview(campaign_id: str) -> str:
    """Get campaign HTML preview."""
    try:
        client = get_client()
        result = await client.get_campaign_preview(int(campaign_id))

        preview_data = result.get("data", {})
        preview_html = preview_data.get("preview", "No preview available")

        return f"""# Campaign Preview

**Campaign ID:** {campaign_id}

## HTML Preview
```html
{preview_html}
```

*This is the rendered HTML content that will be sent to subscribers.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving campaign preview {campaign_id}: {str(e)}"


# List Resources
@mcp.resource("listmonk://lists")
async def list_mailing_lists() -> str:
    """List all mailing lists with basic information."""
    try:
        client = get_client()
        result = await client.get_lists()

        data = result.get("data", {})
        lists = data.get("results", []) if isinstance(data, dict) else data

        list_items = []
        for lst in lists:
            subscriber_count = lst.get('subscriber_count', 0)
            # status = lst.get('status', 'active')  # unused
            tags = lst.get('tags', [])
            tags_str = ", ".join(tags) if tags else "None"

            list_items.append(
                f"- **{lst.get('name')}** (ID: {lst.get('id')}) - Type: {lst.get('type')} - Subscribers: {subscriber_count} - Tags: {tags_str}"
            )

        list_items_text = "\n".join(list_items)

        return f"""# Mailing Lists

**Total Lists:** {len(lists)}

{list_items_text}

*Use the get_list_by_id resource for detailed information.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving mailing lists: {str(e)}"


@mcp.resource("listmonk://list/{list_id}")
async def get_list_by_id(list_id: str) -> str:
    """Get mailing list details by ID."""
    try:
        client = get_client()
        result = await client.get_list(int(list_id))

        list_data = result.get("data", {})

        # Format tags
        tags = list_data.get('tags', [])
        tags_str = ", ".join(tags) if tags else "None"

        return f"""# Mailing List Details

**ID:** {list_data.get('id')}
**Name:** {list_data.get('name')}
**Type:** {list_data.get('type', 'public')}
**Opt-in:** {list_data.get('optin', 'single')}
**Status:** {list_data.get('status', 'active')}

## Statistics
**Subscriber Count:** {list_data.get('subscriber_count', 0)}

## Details
**Created:** {list_data.get('created_at')}
**Updated:** {list_data.get('updated_at')}

## Tags
{tags_str}

## Description
{list_data.get('description', 'No description provided')}

*Use get_list_subscribers_tool to see subscribers for this list.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving list {list_id}: {str(e)}"


@mcp.resource("listmonk://list/{list_id}/subscribers")
async def get_list_subscribers_resource(list_id: str) -> str:
    """Get subscribers for a specific mailing list."""
    try:
        client = get_client()
        result = await client.get_list_subscribers(int(list_id), per_page=50)

        data = result.get("data", {})
        subscribers = data.get("results", [])
        total = data.get("total", 0)

        subscriber_list = []
        for sub in subscribers:
            status = sub.get('status', 'unknown')
            created = sub.get('created_at', 'Unknown')

            subscriber_list.append(
                f"- **{sub.get('name')}** ({sub.get('email')}) - Status: {status} - Joined: {created}"
            )

        subscriber_items = "\n".join(subscriber_list) if subscriber_list else "No subscribers in this list"

        return f"""# List Subscribers

**List ID:** {list_id}
**Total Subscribers:** {total}
**Showing:** {len(subscribers)} subscribers

{subscriber_items}

*Use the get_subscriber_by_id or get_subscriber_by_email resources for detailed subscriber information.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving subscribers for list {list_id}: {str(e)}"


# Template Management Tools
@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_templates(no_body: bool | None = None) -> dict[str, Any]:
    """
    Get all email templates.

    Returns a list of all templates with their IDs, names, types, and default status.
    """
    async def _get_templates_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_templates(no_body=no_body)

        data = result.get("data", {})
        templates = data.get("results", []) if isinstance(data, dict) else data

        return collection_response("templates", templates)

    return await safe_execute_async(_get_templates_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_template(template_id: int, no_body: bool | None = None) -> dict[str, Any]:
    """
    Get a specific template by ID including its full body content.

    Args:
        template_id: ID of the template to retrieve
        no_body: Return template without body content
    """
    async def _get_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_template(template_id, no_body=no_body)

        template = result.get("data", {})
        return success_response("Template retrieved", template=template)

    return await safe_execute_async(_get_template_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def create_template(
    name: str,
    subject: str,
    body: str,
    type: str = "campaign",
    is_default: bool = False,
    body_source: str | None = None
) -> dict[str, Any]:
    """
    Create a new email template.

    Args:
        name: Template name
        subject: Default subject required by the Listmonk templates API
        body: Template HTML body content
        type: Template type (campaign, tx)
        is_default: Whether this is the default template
        body_source: JSON source for campaign_visual templates
    """
    async def _create_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_template(
            name=name,
            subject=subject,
            body=body,
            type=type,
            is_default=is_default,
            body_source=body_source
        )

        template_data = result.get("data", {})
        template_id = template_data.get("id", "unknown")
        return success_response(
            "Template created",
            template_id=template_id,
            template=template_data,
        )

    return await safe_execute_async(_create_template_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def update_template(
    template_id: int,
    name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    is_default: bool | None = None,
    type: str | None = None,
    body_source: str | None = None
) -> dict[str, Any]:
    """
    Update an existing email template.

    Args:
        template_id: ID of the template to update
        name: New template name
        subject: New default template subject
        body: New template HTML body content
        is_default: Whether this is the default template
        type: New template type (campaign, campaign_visual, tx)
        body_source: JSON source for campaign_visual templates
    """
    async def _update_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_template(
            template_id=template_id,
            name=name,
            subject=subject,
            body=body,
            is_default=is_default,
            type=type,
            body_source=body_source
        )

        return success_response(
            "Template updated",
            template_id=template_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_template_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_template(template_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete an email template.

    Args:
        template_id: ID of the template to delete
        confirm: Must be true to delete the template
    """
    async def _delete_template_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete template", template_id=template_id):
            return error
        client = get_client()
        result = await client.delete_template(template_id)

        return success_response(
            "Template deleted",
            template_id=template_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_delete_template_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def preview_template(
    body: str,
    template_type: str = "campaign"
) -> dict[str, Any]:
    """
    Preview a template body without saving it.

    Args:
        body: Template body
        template_type: Template type
    """
    async def _preview_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.preview_template(body=body, template_type=template_type)
        return success_response("Template preview rendered", preview=result.get("text", result.get("data", result)))

    return await safe_execute_async(_preview_template_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_template_html_preview(
    template_id: int,
    body: str | None = None,
    template_type: str = "campaign"
) -> dict[str, Any]:
    """
    Get or render a template HTML preview.

    Args:
        template_id: ID of the template
        body: Optional body override for rendering
        template_type: Template type
    """
    async def _get_preview_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_template_preview(
            template_id=template_id,
            body=body,
            template_type=template_type
        )
        return success_response("Template preview retrieved", template_id=template_id, preview=result.get("text", result.get("data", result)))

    return await safe_execute_async(_get_preview_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def set_default_template(template_id: int) -> dict[str, Any]:
    """
    Set a template as the default template.

    Args:
        template_id: ID of the template
    """
    async def _set_default_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.set_default_template(template_id)
        return success_response("Default template updated", template_id=template_id, template=result.get("data", result))

    return await safe_execute_async(_set_default_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=EMAIL_SEND_TOOL)
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
    confirm_send: bool = False
) -> dict[str, Any]:
    """
    Send a transactional email using a template.

    Args:
        template_id: ID of the template to use
        subscriber_email: Recipient email address
        subscriber_id: Recipient subscriber ID
        subscriber_emails: Multiple recipient email addresses
        subscriber_ids: Multiple recipient subscriber IDs
        subscriber_mode: Recipient lookup mode (default, fallback, external)
        from_email: Optional sender email
        subject: Optional subject override
        data: Template variables/data
        headers: Optional email headers
        messenger: Messenger backend
        content_type: Content type (html, markdown, plain)
        altbody: Optional plain text alternative body
        confirm_send: Must be true to send the transactional email
    """
    async def _send_transactional_logic() -> dict[str, Any]:
        if error := send_confirmation_required(
            confirm_send,
            "send transactional email",
            template_id=template_id,
            subscriber_email=subscriber_email,
            subscriber_id=subscriber_id,
            subscriber_emails=subscriber_emails,
            subscriber_ids=subscriber_ids,
        ):
            return error
        client = get_client()
        result = await client.send_transactional_email(
            template_id=template_id,
            subscriber_email=subscriber_email,
            subscriber_id=subscriber_id,
            subscriber_emails=subscriber_emails,
            subscriber_ids=subscriber_ids,
            subscriber_mode=subscriber_mode,
            from_email=from_email,
            subject=subject,
            data=data or {},
            headers=headers,
            messenger=messenger,
            content_type=content_type,
            altbody=altbody
        )

        return success_response(
            "Transactional email sent",
            subscriber_email=subscriber_email,
            template_id=template_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_send_transactional_logic)  # type: ignore[no-any-return]


# Template Resources
@mcp.resource("listmonk://templates")
async def list_templates() -> str:
    """List all email templates."""
    try:
        client = get_client()
        result = await client.get_templates()

        data = result.get("data", {})
        templates = data.get("results", []) if isinstance(data, dict) else data

        template_list = []
        for template in templates:
            template_type = template.get('type', 'campaign')
            is_default = template.get('is_default', False)
            default_marker = " (DEFAULT)" if is_default else ""

            template_list.append(
                f"- **{template.get('name')}** (ID: {template.get('id')}) - Type: {template_type}{default_marker}"
            )

        template_items = "\n".join(template_list)

        return f"""# Email Templates

**Total Templates:** {len(templates)}

{template_items}

*Use the get_template_by_id resource for detailed template information.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving templates: {str(e)}"


@mcp.resource("listmonk://template/{template_id}")
async def get_template_by_id(template_id: str) -> str:
    """Get template details by ID."""
    try:
        client = get_client()
        result = await client.get_template(int(template_id))

        template = result.get("data", {})

        # Format the body content preview (truncate if too long)
        body = template.get('body', '')
        body_preview = body[:500] + "..." if len(body) > 500 else body

        return f"""# Template Details

**ID:** {template.get('id')}
**Name:** {template.get('name')}
**Type:** {template.get('type', 'campaign')}
**Default:** {"Yes" if template.get('is_default') else "No"}

## Timing
**Created:** {template.get('created_at')}
**Updated:** {template.get('updated_at')}

## Template Body Preview
```html
{body_preview}
```

*Note: Body content may be truncated for display. Use the template in campaigns or transactional emails to see full content.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving template {template_id}: {str(e)}"


@mcp.resource("listmonk://template/{template_id}/preview")
async def get_template_preview(template_id: str) -> str:
    """Get full template body content."""
    try:
        client = get_client()
        result = await client.get_template(int(template_id))

        template = result.get("data", {})
        body = template.get('body', 'No content available')

        return f"""# Template Full Content

**Template ID:** {template_id}
**Template Name:** {template.get('name')}

## Full HTML Body
```html
{body}
```

*This is the complete template HTML that can be used for campaigns and transactional emails.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving template content {template_id}: {str(e)}"


# Media Management Tools
@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_media_list() -> dict[str, Any]:
    """
    Get all media files from Listmonk.

    Returns a list of all uploaded media with their IDs, filenames, URLs, and metadata.
    """
    async def _get_media_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_media()

        if not isinstance(result, dict):
            return {
                "success": False,
                "error": {
                    "error_type": "UnexpectedResponseError",
                    "message": "Unexpected response type from Listmonk",
                    "response_type": type(result).__name__,
                },
            }

        data = result.get("data", [])

        # Handle both list and dict formats (Listmonk can return either)
        if isinstance(data, dict):
            if not data:
                return collection_response("media", [])
            media_list = list(data.values())
        else:
            media_list = data

        if media_list and isinstance(media_list[0], list):
            media_list = media_list[0]

        return collection_response("media", media_list)

    return await safe_execute_async(_get_media_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=READ_ONLY_TOOL)
async def get_media_file(media_id: int) -> dict[str, Any]:
    """
    Get a specific uploaded media file.

    Args:
        media_id: ID of the media file
    """
    async def _get_media_file_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_media_file(media_id)
        return success_response("Media retrieved", media_id=media_id, media=result.get("data", result))

    return await safe_execute_async(_get_media_file_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def upload_media_file(
    file_path: str,
    title: str | None = None
) -> dict[str, Any]:
    """
    Upload a media file to Listmonk.

    Args:
        file_path: Absolute path to the image file to upload
        title: Optional title/description for the media (defaults to filename)

    Returns:
        Success message with the uploaded file's URL
    """
    async def _upload_media_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.upload_media(file_path, title)

        media_data = result.get("data", {})
        media_id = media_data.get("id", "unknown")

        return success_response(
            "Media uploaded",
            media_id=media_id,
            media=media_data,
        )

    return await safe_execute_async(_upload_media_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def rename_media(media_id: int, new_title: str) -> dict[str, Any]:
    """
    Rename/update the title of a media file.

    Args:
        media_id: ID of the media file to rename
        new_title: New title/description for the media file

    Returns:
        Success message
    """
    async def _rename_media_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_media(media_id, new_title)

        return success_response(
            "Media renamed",
            media_id=media_id,
            title=new_title,
            result=result.get("data", result),
        )

    return await safe_execute_async(_rename_media_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_media_file(media_id: int, confirm: bool = False) -> dict[str, Any]:
    """
    Delete a media file from Listmonk.

    Args:
        media_id: ID of the media file to delete
        confirm: Must be true to delete the media file

    Returns:
        Success message
    """
    async def _delete_media_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete media file", media_id=media_id):
            return error
        client = get_client()
        result = await client.delete_media(media_id)

        return success_response(
            "Media deleted",
            media_id=media_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_delete_media_logic)  # type: ignore[no-any-return]


# Media Resources
@mcp.resource("listmonk://media")
async def list_media_files() -> str:
    """List all media files with details."""
    try:
        client = get_client()
        result = await client.get_media()

        data = result.get("data", [])

        # Handle both list and dict formats
        if isinstance(data, dict):
            if not data:
                return "# Media Files\n\nNo media files found."
            media_list = list(data.values())
        else:
            media_list = data

        # Flatten if the first element is itself a list (nested structure)
        if media_list and isinstance(media_list[0], list):
            media_list = media_list[0]

        if not media_list:
            return "# Media Files\n\nNo media files found."

        media_items = []
        for media in media_list:
            size_bytes = media.get('meta', {}).get('size', 0) if isinstance(media.get('meta'), dict) else 0
            size_kb = size_bytes / 1024 if size_bytes > 0 else 0
            created = media.get('created_at', 'Unknown')
            media_items.append(
                f"- **{media.get('filename')}** (ID: {media.get('id')})\n"
                f"  - Title: {media.get('title', media.get('filename', 'No title'))}\n"
                f"  - Size: {size_kb:.1f} KB\n"
                f"  - Created: {created}\n"
                f"  - URL: {media.get('url', 'No URL')}"
            )

        media_items_text = "\n\n".join(media_items)

        return f"""# Media Files

**Total Files:** {len(media_list)}

{media_items_text}

*Use upload_media_file to add new files, rename_media to update titles, or delete_media_file to remove files.*
"""

    except ListmonkAPIError as e:
        return f"Error retrieving media files: {str(e)}"


# Campaign Body Editing Tools

@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def replace_in_campaign_body(
    campaign_id: int,
    search: str,
    replace: str
) -> dict[str, Any]:
    """
    Search and replace text in a campaign body (simple string matching).

    This is much more token-efficient than updating the entire campaign body.

    Args:
        campaign_id: ID of the campaign to edit
        search: Text to search for (exact string match)
        replace: Text to replace it with

    Returns:
        Success message with number of replacements made

    Example:
        replace_in_campaign_body(
            campaign_id=11,
            search="</p>",
            replace="</p>\n<img src='https://...' style='...'>"
        )
    """
    async def _replace_logic() -> dict[str, Any]:
        client = get_client()

        # Fetch current campaign
        result = await client.get_campaign(campaign_id)
        campaign = result.get("data", {})

        if not campaign:
            return {
                "success": False,
                "error": {
                    "error_type": "ResourceNotFoundError",
                    "message": f"Campaign {campaign_id} not found",
                    "campaign_id": campaign_id,
                },
            }

        current_body = campaign.get("body", "")

        # Perform replacement
        new_body = current_body.replace(search, replace)
        count = current_body.count(search)

        if count == 0:
            return success_response(
                "Search text not found",
                campaign_id=campaign_id,
                replacements=0,
            )

        update_result = await client.update_campaign(
            campaign_id=campaign_id,
            name=campaign.get("name"),
            subject=campaign.get("subject"),
            lists=[lst["id"] for lst in campaign.get("lists", [])],
            body=new_body
        )

        return success_response(
            "Campaign body updated",
            campaign_id=campaign_id,
            replacements=count,
            result=update_result.get("data", update_result),
        )

    return await safe_execute_async(_replace_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def regex_replace_in_campaign_body(
    campaign_id: int,
    pattern: str,
    replace: str
) -> dict[str, Any]:
    """
    Search and replace in campaign body using regex patterns.

    More powerful than simple replace - supports capturing groups and complex patterns.

    Args:
        campaign_id: ID of the campaign to edit
        pattern: Regex pattern to search for
        replace: Replacement string (can use \\1, \\2 for capture groups)

    Returns:
        Success message with number of replacements made

    Example:
        regex_replace_in_campaign_body(
            campaign_id=11,
            pattern=r"(Bondeni.*?</p>)",
            replace=r"\\1\n<img src='https://...'>"
        )
    """
    async def _regex_replace_logic() -> dict[str, Any]:
        import re

        client = get_client()

        # Fetch current campaign
        result = await client.get_campaign(campaign_id)
        campaign = result.get("data", {})

        if not campaign:
            return {
                "success": False,
                "error": {
                    "error_type": "ResourceNotFoundError",
                    "message": f"Campaign {campaign_id} not found",
                    "campaign_id": campaign_id,
                },
            }

        current_body = campaign.get("body", "")

        # Perform regex replacement
        new_body, count = re.subn(pattern, replace, current_body)

        if count == 0:
            return success_response(
                "Pattern not found",
                campaign_id=campaign_id,
                replacements=0,
            )

        update_result = await client.update_campaign(
            campaign_id=campaign_id,
            name=campaign.get("name"),
            subject=campaign.get("subject"),
            lists=[lst["id"] for lst in campaign.get("lists", [])],
            body=new_body
        )

        return success_response(
            "Campaign body updated",
            campaign_id=campaign_id,
            replacements=count,
            result=update_result.get("data", update_result),
        )

    return await safe_execute_async(_regex_replace_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=SIDE_EFFECT_TOOL)
async def batch_replace_in_campaign_body(
    campaign_id: int,
    replacements: CampaignBodyReplacementsPayload
) -> dict[str, Any]:
    """
    Perform multiple search-and-replace operations in one go.

    Even more efficient - fetches campaign once, does all replacements, updates once.

    Args:
        campaign_id: ID of the campaign to edit
        replacements: List of dicts with 'search' and 'replace' keys

    Returns:
        Success message with total replacements made

    Example:
        batch_replace_in_campaign_body(
            campaign_id=11,
            replacements=[
                {"search": "Text A", "replace": "Text B"},
                {"search": "Text C", "replace": "Text D"}
            ]
        )
    """
    async def _batch_replace_logic() -> dict[str, Any]:
        client = get_client()

        # Fetch current campaign
        result = await client.get_campaign(campaign_id)
        campaign = result.get("data", {})

        if not campaign:
            return {
                "success": False,
                "error": {
                    "error_type": "ResourceNotFoundError",
                    "message": f"Campaign {campaign_id} not found",
                    "campaign_id": campaign_id,
                },
            }

        current_body = campaign.get("body", "")
        new_body = current_body
        total_count = 0

        # Perform all replacements
        for replacement in replacements:
            search = replacement.get("search", "")
            replace = replacement.get("replace", "")

            if not search:
                continue

            count = new_body.count(search)
            new_body = new_body.replace(search, replace)
            total_count += count

        if total_count == 0:
            return success_response(
                "No search texts found",
                campaign_id=campaign_id,
                replacement_operations=len(replacements),
                replacements=0,
            )

        update_result = await client.update_campaign(
            campaign_id=campaign_id,
            name=campaign.get("name"),
            subject=campaign.get("subject"),
            lists=[lst["id"] for lst in campaign.get("lists", [])],
            body=new_body
        )

        return success_response(
            "Campaign body updated",
            campaign_id=campaign_id,
            replacement_operations=len(replacements),
            replacements=total_count,
            result=update_result.get("data", update_result),
        )

    return await safe_execute_async(_batch_replace_logic)  # type: ignore[no-any-return]


# Maintenance Tools
@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_gc_subscribers(type: str, confirm: bool = False) -> dict[str, Any]:
    """
    Garbage collect orphaned or blocklisted subscribers.

    Args:
        type: Subscriber GC type from Listmonk maintenance API
        confirm: Must be true to delete garbage-collected subscribers
    """
    async def _delete_gc_subscribers_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete subscriber garbage collection", type=type):
            return error
        client = get_client()
        result = await client.delete_gc_subscribers(type)
        return success_response("Subscriber garbage collection completed", result=result.get("data", result))

    return await safe_execute_async(_delete_gc_subscribers_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_campaign_analytics(type: str, before_date: str, confirm: bool = False) -> dict[str, Any]:
    """
    Delete campaign analytics before a date.

    Args:
        type: Analytics type from Listmonk maintenance API
        before_date: Delete analytics before this date
        confirm: Must be true to delete campaign analytics
    """
    async def _delete_campaign_analytics_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete campaign analytics", type=type, before_date=before_date):
            return error
        client = get_client()
        result = await client.delete_campaign_analytics(type=type, before_date=before_date)
        return success_response("Campaign analytics deleted", result=result.get("data", result))

    return await safe_execute_async(_delete_campaign_analytics_logic)  # type: ignore[no-any-return]


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
async def delete_unconfirmed_subscriptions(before_date: str, confirm: bool = False) -> dict[str, Any]:
    """
    Delete unconfirmed subscriptions before a date.

    Args:
        before_date: Delete subscriptions before this date
        confirm: Must be true to delete unconfirmed subscriptions
    """
    async def _delete_unconfirmed_logic() -> dict[str, Any]:
        if error := confirmation_required(confirm, "delete unconfirmed subscriptions", before_date=before_date):
            return error
        client = get_client()
        result = await client.delete_unconfirmed_subscriptions(before_date)
        return success_response("Unconfirmed subscriptions deleted", result=result.get("data", result))

    return await safe_execute_async(_delete_unconfirmed_logic)  # type: ignore[no-any-return]


# CLI application
cli_app = typer.Typer(
    name="listmonk-mcp-bridge",
    help="Listmonk MCP Server - Connect Claude Code to Listmonk via Model Context Protocol",
    add_completion=False
)


@cli_app.command()
def run(
    config_file: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file (.env format)"
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug logging"
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit"
    )
) -> None:
    """
    Start the Listmonk MCP server.

    The server requires configuration via environment variables:
    - LISTMONK_MCP_URL: Listmonk server URL (e.g., http://localhost:9000)
    - LISTMONK_MCP_USERNAME: Listmonk API username
    - LISTMONK_MCP_PASSWORD: Listmonk API password/token

    Optional environment variables:
    - LISTMONK_MCP_TIMEOUT: Request timeout in seconds (default: 30)
    - LISTMONK_MCP_MAX_RETRIES: Maximum retry attempts (default: 3)
    - LISTMONK_MCP_DEBUG: Enable debug mode (default: false)
    - LISTMONK_MCP_LOG_LEVEL: Logging level (default: INFO)
    """
    if version:
        # Import here to avoid circular imports
        try:
            from importlib.metadata import version as get_version
            pkg_version = get_version("listmonk-mcp-bridge")
        except ImportError:
            pkg_version = "0.0.1"  # fallback
        typer.echo(f"listmonk-mcp-bridge {pkg_version}")
        raise typer.Exit()

    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    try:
        logger.info("Starting Listmonk MCP Server...")
        # Create the production MCP server with lifespan management
        server = create_production_server()
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
        raise typer.Exit(0) from None
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise typer.Exit(1) from e


def main() -> None:
    """Main entry point for the CLI script."""
    cli_app()


if __name__ == "__main__":
    main()
