"""Listmonk MCP Server using FastMCP framework."""

import logging
from contextlib import asynccontextmanager
from typing import Any

import typer
from mcp.server import FastMCP

from .client import ListmonkAPIError, ListmonkClient, create_client
from .config import Config, load_config, validate_config
from .exceptions import safe_execute_async

# Global state
_client: ListmonkClient | None = None
_config: Config | None = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
@mcp.tool()
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


# Subscriber Management Tools
@mcp.tool()
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


@mcp.tool()
async def update_subscriber(
    subscriber_id: int,
    email: str | None = None,
    name: str | None = None,
    status: str | None = None,
    lists: list[int] | None = None,
    attributes: dict[str, Any] | None = None
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
    """
    async def _update_subscriber_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_subscriber(
            subscriber_id=subscriber_id,
            email=email,
            name=name,
            status=status,
            lists=lists,
            attribs=attributes
        )

        return success_response(
            "Subscriber updated",
            subscriber_id=subscriber_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def remove_subscriber(subscriber_id: int) -> dict[str, Any]:
    """
    Remove a subscriber from Listmonk.

    Args:
        subscriber_id: ID of the subscriber to remove
    """
    async def _remove_subscriber_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.delete_subscriber(subscriber_id)

        return success_response(
            "Subscriber removed",
            subscriber_id=subscriber_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_remove_subscriber_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def change_subscriber_status(subscriber_id: int, status: str) -> dict[str, Any]:
    """
    Change subscriber status.

    Args:
        subscriber_id: ID of the subscriber
        status: New status (enabled, disabled, blocklisted)
    """
    async def _change_status_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.set_subscriber_status(subscriber_id, status)

        return success_response(
            "Subscriber status changed",
            subscriber_id=subscriber_id,
            status=status,
            result=result.get("data", result),
        )

    return await safe_execute_async(_change_status_logic)  # type: ignore[no-any-return]


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
@mcp.tool()
async def get_mailing_lists() -> dict[str, Any]:
    """
    Get all mailing lists.

    Returns a list of all mailing lists with their IDs, UUIDs, names, subscriber counts, and types.
    """
    async def _get_lists_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_lists()

        data = result.get("data", {})
        lists = data.get("results", []) if isinstance(data, dict) else data

        return collection_response("mailing_lists", lists)

    return await safe_execute_async(_get_lists_logic)  # type: ignore[no-any-return]


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def delete_mailing_list(list_id: int) -> dict[str, Any]:
    """
    Delete a mailing list.

    Args:
        list_id: ID of the list to delete
    """
    async def _delete_list_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.delete_list(list_id)

        return success_response(
            "Mailing list deleted",
            list_id=list_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_delete_list_logic)  # type: ignore[no-any-return]


@mcp.tool()
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
@mcp.tool()
async def get_campaigns(
    status: str | None = None,
    page: int = 1,
    per_page: int = 20
) -> dict[str, Any]:
    """
    Get all campaigns with optional status filter.

    Args:
        status: Filter by status (draft, running, paused, finished, cancelled)
        page: Page number for pagination
        per_page: Number of campaigns per page
    """
    async def _get_campaigns_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaigns(page=page, per_page=per_page, status=status)

        data = result.get("data", {})
        campaigns = data.get("results", []) if isinstance(data, dict) else data
        total = data.get("total", 0) if isinstance(data, dict) else len(campaigns)

        return collection_response(
            "campaigns",
            campaigns,
            total=total,
            page=page,
            per_page=per_page,
        )

    return await safe_execute_async(_get_campaigns_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def get_campaign(campaign_id: int) -> dict[str, Any]:
    """
    Get a specific campaign by ID including its full body content.

    Args:
        campaign_id: ID of the campaign to retrieve
    """
    async def _get_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_campaign(campaign_id)

        campaign = result.get("data", {})
        return success_response("Campaign retrieved", campaign=campaign)

    return await safe_execute_async(_get_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def create_campaign(
    name: str,
    subject: str,
    lists: list[int],
    type: str = "regular",
    content_type: str = "richtext",
    body: str | None = None,
    template_id: int | None = None,
    tags: list[str] | None = None,
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
        template_id: Template ID to use (optional)
        tags: Campaign tags
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
            template_id=template_id,
            tags=tags or [],
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


@mcp.tool()
async def update_campaign(
    campaign_id: int,
    name: str | None = None,
    subject: str | None = None,
    lists: list[int] | None = None,
    body: str | None = None,
    tags: list[str] | None = None
) -> dict[str, Any]:
    """
    Update an existing campaign.

    Args:
        campaign_id: ID of the campaign to update
        name: New campaign name
        subject: New email subject
        lists: New list of mailing list IDs
        body: New campaign content
        tags: New campaign tags
    """
    async def _update_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_campaign(
            campaign_id=campaign_id,
            name=name,
            subject=subject,
            lists=lists,
            body=body,
            tags=tags
        )

        return success_response(
            "Campaign updated",
            campaign_id=campaign_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def send_campaign(campaign_id: int) -> dict[str, Any]:
    """
    Send a campaign immediately.

    Args:
        campaign_id: ID of the campaign to send
    """
    async def _send_campaign_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.send_campaign(campaign_id)

        return success_response(
            "Campaign sent",
            campaign_id=campaign_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_send_campaign_logic)  # type: ignore[no-any-return]


@mcp.tool()
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
@mcp.tool()
async def get_templates() -> dict[str, Any]:
    """
    Get all email templates.

    Returns a list of all templates with their IDs, names, types, and default status.
    """
    async def _get_templates_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_templates()

        data = result.get("data", {})
        templates = data.get("results", []) if isinstance(data, dict) else data

        return collection_response("templates", templates)

    return await safe_execute_async(_get_templates_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def get_template(template_id: int) -> dict[str, Any]:
    """
    Get a specific template by ID including its full body content.

    Args:
        template_id: ID of the template to retrieve
    """
    async def _get_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.get_template(template_id)

        template = result.get("data", {})
        return success_response("Template retrieved", template=template)

    return await safe_execute_async(_get_template_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def create_template(
    name: str,
    subject: str,
    body: str,
    type: str = "campaign",
    is_default: bool = False
) -> dict[str, Any]:
    """
    Create a new email template.

    Args:
        name: Template name
        subject: Default subject required by the Listmonk templates API
        body: Template HTML body content
        type: Template type (campaign, tx)
        is_default: Whether this is the default template
    """
    async def _create_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.create_template(
            name=name,
            subject=subject,
            body=body,
            type=type,
            is_default=is_default
        )

        template_data = result.get("data", {})
        template_id = template_data.get("id", "unknown")
        return success_response(
            "Template created",
            template_id=template_id,
            template=template_data,
        )

    return await safe_execute_async(_create_template_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def update_template(
    template_id: int,
    name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    is_default: bool | None = None
) -> dict[str, Any]:
    """
    Update an existing email template.

    Args:
        template_id: ID of the template to update
        name: New template name
        subject: New default template subject
        body: New template HTML body content
        is_default: Whether this is the default template
    """
    async def _update_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.update_template(
            template_id=template_id,
            name=name,
            subject=subject,
            body=body,
            is_default=is_default
        )

        return success_response(
            "Template updated",
            template_id=template_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_update_template_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def delete_template(template_id: int) -> dict[str, Any]:
    """
    Delete an email template.

    Args:
        template_id: ID of the template to delete
    """
    async def _delete_template_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.delete_template(template_id)

        return success_response(
            "Template deleted",
            template_id=template_id,
            result=result.get("data", result),
        )

    return await safe_execute_async(_delete_template_logic)  # type: ignore[no-any-return]


@mcp.tool()
async def send_transactional_email(
    template_id: int,
    subscriber_email: str,
    data: dict[str, Any] | None = None,
    content_type: str = "html"
) -> dict[str, Any]:
    """
    Send a transactional email using a template.

    Args:
        template_id: ID of the template to use
        subscriber_email: Recipient email address
        data: Template variables/data
        content_type: Content type (html, plain)
    """
    async def _send_transactional_logic() -> dict[str, Any]:
        client = get_client()
        result = await client.send_transactional_email(
            template_id=template_id,
            subscriber_email=subscriber_email,
            data=data or {},
            content_type=content_type
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
@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def delete_media_file(media_id: int) -> dict[str, Any]:
    """
    Delete a media file from Listmonk.

    Args:
        media_id: ID of the media file to delete

    Returns:
        Success message
    """
    async def _delete_media_logic() -> dict[str, Any]:
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

@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def batch_replace_in_campaign_body(
    campaign_id: int,
    replacements: list[dict[str, str]]
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
