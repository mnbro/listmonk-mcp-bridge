from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkAPIError, ListmonkClient
from listmonk_mcp.config import Config


def test_default_mode_is_agentic_in_fresh_process() -> None:
    env = os.environ.copy()
    env.pop("LISTMONK_MCP_MODE", None)
    env.pop("LISTMONK_MCP_READ_ONLY", None)
    code = """
import asyncio, json
from listmonk_mcp import server
async def main():
    tools = sorted(tool.name for tool in await server.mcp.list_tools())
    resources = sorted(str(resource.uri) for resource in await server.mcp.list_resources())
    print(json.dumps({
        "mode": server._raw_mcp_mode(),
        "readOnly": server._read_only_enabled(),
        "tools": tools,
        "resources": resources,
        "hidden": sorted(server.HIDDEN_FULL_MODE_TOOL_NAMES),
        "hiddenResources": sorted(server.HIDDEN_FULL_MODE_RESOURCE_URIS),
    }))
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["mode"] == "agentic"
    assert payload["readOnly"] is True
    assert "safe_send_campaign" in payload["tools"]
    assert "send_campaign" not in payload["tools"]
    assert "send_campaign" in payload["hidden"]
    assert "listmonk://capabilities" in payload["resources"]
    assert "listmonk://subscriber/{subscriber_id}" not in payload["resources"]
    assert "listmonk://subscriber/{subscriber_id}" in payload["hiddenResources"]


@pytest.mark.asyncio
async def test_read_only_blocks_write_before_client_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class ExplodingClient:
        async def send_campaign(self, campaign_id: int) -> dict[str, Any]:
            raise AssertionError("client should not be called")

    monkeypatch.setenv("LISTMONK_MCP_READ_ONLY", "true")
    monkeypatch.setenv("LISTMONK_MCP_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(server, "get_client", lambda: ExplodingClient())

    result = await server.send_campaign(campaign_id=123, confirm_send=True)

    assert result["success"] is False
    assert result["error"]["type"] == "read_only"
    assert result["blockers"] == ["Write mode is disabled"]


@pytest.mark.asyncio
async def test_dry_run_helper_allowed_in_read_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LISTMONK_MCP_READ_ONLY", "true")

    result = await server.safe_create_campaign_draft(
        name="Draft",
        subject="Subject",
        listIds=[1],
        body="Hello",
        dryRun=True,
    )

    assert result["success"] is True
    assert result["dryRun"] is True


@pytest.mark.asyncio
async def test_capability_report_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LISTMONK_MCP_READ_ONLY", "true")
    monkeypatch.setenv("LISTMONK_MCP_PASSWORD", "super-secret")
    monkeypatch.setenv("LISTMONK_MCP_URL", "https://listmonk.example.com")
    monkeypatch.setenv("LISTMONK_MCP_USERNAME", "api-user")

    result = await server.listmonk_capability_report()
    encoded = json.dumps(result)

    assert result["success"] is True
    assert result["readOnly"] is True
    assert result["upstream"]["baseUrlHost"] == "listmonk.example.com"
    assert "super-secret" not in encoded
    assert result["riskClassCounts"]


@pytest.mark.asyncio
async def test_prompts_are_registered() -> None:
    prompts = {prompt.name for prompt in await server.mcp.list_prompts()}

    assert {
        "inspect_listmonk_audience",
        "create_campaign_safely",
        "send_campaign_safely",
        "import_subscribers_safely",
        "review_campaign_performance",
        "debug_listmonk_connection",
    }.issubset(prompts)


def test_every_registered_tool_has_risk_class() -> None:
    missing = server.ALL_TOOL_NAMES - set(server.TOOL_RISK_CLASSES)

    assert missing == set()


@pytest.mark.asyncio
async def test_get_retries_but_post_does_not_retry() -> None:
    class FlakyTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(request.method)
            if len(self.calls) == 1:
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(200, json={"data": {"ok": True}})

    config = Config(url="http://localhost:9000", username="u", password="p")
    config.max_retries = 1

    get_transport = FlakyTransport()
    get_client = ListmonkClient(config)
    get_client._client = httpx.AsyncClient(transport=get_transport)
    assert await get_client._request("GET", "/api/health") == {"data": {"ok": True}}
    assert get_transport.calls == ["GET", "GET"]
    await get_client.close()

    post_transport = FlakyTransport()
    post_client = ListmonkClient(config)
    post_client._client = httpx.AsyncClient(transport=post_transport)
    with pytest.raises(ListmonkAPIError):
        await post_client._request("POST", "/api/campaigns/1/status")
    assert post_transport.calls == ["POST"]
    await post_client.close()
