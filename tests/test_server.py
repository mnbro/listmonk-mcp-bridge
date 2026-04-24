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
