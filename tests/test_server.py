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

    assert set(tools["update_settings"]["properties"]) == {"settings"}
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
