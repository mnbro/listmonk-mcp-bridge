from typing import Any

import pytest

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkAPIError
from listmonk_mcp.exceptions import safe_execute_async


class FakeListmonkClient:
    async def get_list_subscribers(
        self,
        list_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        return {
            "data": {
                "results": [
                    {
                        "id": 1,
                        "email": "ada@example.com",
                        "name": "Ada Lovelace",
                        "status": "enabled",
                    },
                    {
                        "id": 2,
                        "email": "grace@example.com",
                        "name": "Grace Hopper",
                        "status": "enabled",
                    },
                ],
                "total": 2,
            }
        }


def test_create_production_server_returns_registered_server() -> None:
    assert server.create_production_server() is server.mcp


@pytest.mark.asyncio
async def test_reported_tool_schemas_include_documented_arguments() -> None:
    tools = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    assert set(tools["update_settings"]["properties"]) == {"settings", "confirm"}
    assert tools["update_settings"]["required"] == ["settings"]
    assert tools["update_settings"]["properties"]["settings"]["type"] == "object"
    assert "smtp" in tools["update_settings"]["properties"]["settings"]["properties"]

    assert set(tools["test_smtp_settings"]["properties"]) == {"settings"}
    assert tools["test_smtp_settings"]["required"] == ["settings"]
    assert tools["test_smtp_settings"]["properties"]["settings"]["type"] == "object"
    assert "host" in tools["test_smtp_settings"]["properties"]["settings"]["properties"]

    assert set(tools["import_subscribers"]["properties"]) == {"file_path", "params"}
    assert tools["import_subscribers"]["required"] == ["file_path", "params"]
    import_params = tools["import_subscribers"]["properties"]["params"]
    assert import_params["required"] == ["mode", "delim"]
    assert import_params["properties"]["mode"]["enum"] == ["subscribe", "blocklist"]

    assert set(tools["batch_replace_in_campaign_body"]["properties"]) == {"campaign_id", "replacements"}
    assert tools["batch_replace_in_campaign_body"]["required"] == ["campaign_id", "replacements"]
    replacement_items = tools["batch_replace_in_campaign_body"]["properties"]["replacements"]["items"]
    assert replacement_items["required"] == ["search", "replace"]
    assert set(replacement_items["properties"]) == {"search", "replace"}


@pytest.mark.asyncio
async def test_destructive_tools_are_annotated_and_require_confirmation() -> None:
    destructive_tools = {
        "delete_subscriber_bounces",
        "blocklist_subscriber",
        "blocklist_subscribers",
        "delete_subscribers_by_query",
        "blocklist_subscribers_by_query",
        "update_subscriber",
        "manage_subscriber_lists",
        "manage_subscriber_lists_by_query",
        "change_subscriber_status",
        "remove_subscriber",
        "remove_subscribers",
        "delete_bounce",
        "delete_bounces",
        "delete_mailing_list",
        "delete_mailing_lists",
        "delete_campaign",
        "delete_campaigns",
        "delete_template",
        "delete_media_file",
        "stop_import_subscribers",
        "delete_gc_subscribers",
        "delete_campaign_analytics",
        "delete_unconfirmed_subscriptions",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    for tool_name in destructive_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is True
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.idempotentHint is False
        assert tool.inputSchema["properties"]["confirm"]["type"] == "boolean"

    result = await server.delete_campaign(campaign_id=7)

    assert result["success"] is False
    assert result["error"]["error_type"] == "ConfirmationRequired"
    assert result["error"]["confirm_required"] is True
    assert result["error"]["context"] == {"campaign_id": 7}

    result = await server.change_subscriber_status(subscriber_id=11, status="blocklisted")

    assert result["success"] is False
    assert result["error"]["error_type"] == "ConfirmationRequired"


@pytest.mark.asyncio
async def test_email_sending_tools_are_marked_side_effecting_and_require_confirmation() -> None:
    email_tools = {
        "send_subscriber_optin",
        "send_campaign",
        "test_campaign",
        "send_transactional_email",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    for tool_name in email_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is False
        assert tool.annotations.openWorldHint is True
        assert tool.inputSchema["properties"]["confirm_send"]["type"] == "boolean"

    result = await server.send_campaign(campaign_id=7)

    assert result["success"] is False
    assert result["error"]["error_type"] == "SendConfirmationRequired"
    assert result["error"]["confirm_required"] is True


@pytest.mark.asyncio
async def test_read_only_tools_are_explicitly_annotated() -> None:
    read_only_tools = {
        "check_listmonk_health",
        "get_server_config",
        "get_i18n_language",
        "get_dashboard_charts",
        "get_dashboard_counts",
        "get_settings",
        "get_logs",
        "get_subscribers",
        "get_subscriber",
        "get_subscriber_export",
        "get_subscriber_bounces",
        "get_bounces",
        "get_bounce",
        "get_mailing_lists",
        "get_public_mailing_lists",
        "get_mailing_list",
        "get_import_subscribers",
        "get_import_subscriber_logs",
        "get_list_subscribers_tool",
        "get_campaigns",
        "get_campaign",
        "get_campaign_html_preview",
        "preview_campaign_body",
        "preview_campaign_text",
        "get_running_campaign_stats",
        "get_campaign_analytics",
        "get_templates",
        "get_template",
        "preview_template",
        "get_template_html_preview",
        "get_media_list",
        "get_media_file",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    assert all(tool.annotations is not None for tool in tools.values())
    for tool_name in read_only_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True


def test_success_response() -> None:
    assert server.success_response("Done", resource_id=42) == {
        "success": True,
        "message": "Done",
        "resource_id": 42,
    }


def test_collection_response() -> None:
    assert server.collection_response(
        "subscribers",
        [{"id": 1}],
        total=10,
        page=2,
        per_page=1,
    ) == {
        "success": True,
        "resource": "subscribers",
        "count": 1,
        "items": [{"id": 1}],
        "total": 10,
        "page": 2,
        "per_page": 1,
    }


@pytest.mark.asyncio
async def test_get_list_subscribers_tool_returns_subscribers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_client", lambda: FakeListmonkClient())

    result = await server.get_list_subscribers_tool(list_id=7, page=2, per_page=10)

    assert result == {
        "success": True,
        "list_id": 7,
        "page": 2,
        "per_page": 10,
        "count": 2,
        "total": 2,
        "subscribers": [
            {
                "id": 1,
                "email": "ada@example.com",
                "name": "Ada Lovelace",
                "status": "enabled",
            },
            {
                "id": 2,
                "email": "grace@example.com",
                "name": "Grace Hopper",
                "status": "enabled",
            },
        ],
    }


@pytest.mark.asyncio
async def test_safe_execute_async_returns_structured_api_errors() -> None:
    async def failing_tool() -> None:
        raise ListmonkAPIError("connection failed")

    result = await safe_execute_async(failing_tool)

    assert result == {
        "success": False,
        "error": {
            "error_type": "APIError",
            "message": "connection failed",
        },
    }


@pytest.mark.asyncio
async def test_safe_execute_async_does_not_return_traceback() -> None:
    async def failing_tool() -> None:
        raise RuntimeError("boom")

    result = await safe_execute_async(failing_tool)

    assert result["success"] is False
    assert result["error"]["error_type"] == "OperationError"
    assert result["error"]["message"] == "Unexpected error while executing MCP tool"
    assert result["error"]["operation"] == "failing_tool"
    assert result["error"]["details"] == {"error": "boom"}
    assert "Traceback" not in str(result)
