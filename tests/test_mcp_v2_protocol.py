from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from listmonk_mcp import server
from listmonk_mcp.mcp_adapter import MCPRuntime, MCPServerType, ToolHints


@asynccontextmanager
async def empty_lifespan(app: MCPServerType) -> AsyncIterator[None]:
    del app
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_bridge_serves_modern_and_legacy_protocols(mode: str) -> None:
    async with Client(server.mcp, mode=mode) as client:
        tools_result = await client.list_tools(cache_mode="refresh")
        prompts_result = await client.list_prompts()
        resources_result = await client.list_resources()
        call_result = await client.call_tool(
            "listmonk_capability_report",
            {},
        )

        if mode == "legacy":
            assert client.protocol_version == "2025-11-25"
        else:
            assert client.protocol_version is not None
            assert client.protocol_version != "2025-11-25"

    tools = {tool.name: tool for tool in tools_result.tools}
    import_tool = tools["prepare_subscriber_import"]
    assert import_tool.annotations is not None
    assert import_tool.annotations.read_only_hint is True
    assert import_tool.input_schema["properties"]["filePreview"]["type"] == "string"

    wire_tool = import_tool.model_dump(by_alias=True, exclude_none=True)
    assert "inputSchema" in wire_tool
    assert wire_tool["annotations"]["readOnlyHint"] is True
    assert "prepare_subscriber_import" in tools
    assert "debug_listmonk_connection" in {
        prompt.name for prompt in prompts_result.prompts
    }
    assert "listmonk://capabilities" in {
        str(resource.uri) for resource in resources_result.resources
    }

    assert call_result.is_error is False
    assert call_result.structured_content is not None
    assert call_result.structured_content["success"] is True
    assert call_result.structured_content["transport"] == "stdio"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_protocol"),
    [("auto", "2026-07-28"), ("legacy", "2025-11-25")],
)
async def test_installed_console_serves_stdio_protocol(
    mode: str,
    expected_protocol: str,
) -> None:
    child_env = os.environ.copy()
    child_env.update(
        {
            "LISTMONK_MCP_MODE": "agentic",
            "LISTMONK_MCP_READ_ONLY": "true",
            "PYTHONWARNINGS": "error",
        }
    )
    params = StdioServerParameters(
        command="listmonk-mcp-bridge",
        env=child_env,
    )

    async def probe() -> tuple[str | None, set[str]]:
        async with Client(stdio_client(params), mode=mode) as client:
            tools_result = await client.list_tools(cache_mode="refresh")
            return client.protocol_version, {tool.name for tool in tools_result.tools}

    protocol_version, tool_names = await asyncio.wait_for(probe(), timeout=10)

    assert protocol_version == expected_protocol
    assert "listmonk_capability_report" in tool_names


@pytest.mark.asyncio
async def test_application_lifespan_owns_shared_client_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CloseTrackingClient:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    shared_client = CloseTrackingClient()
    monkeypatch.setattr(server, "_client", shared_client)

    async with Client(server.mcp) as client:
        await client.list_tools(cache_mode="refresh")
        await client.list_tools(cache_mode="refresh")
        assert shared_client.close_calls == 0

    assert shared_client.close_calls == 1
    assert server._client is None


@pytest.mark.asyncio
async def test_client_cancellation_reaches_server_handler() -> None:
    runtime = MCPRuntime(name="cancellation-test", lifespan=empty_lifespan)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    @runtime.tool(
        annotations=ToolHints(
            read_only=True,
            destructive=False,
            idempotent=True,
        )
    )
    async def wait_until_cancelled() -> str:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "completed"

    async with Client(runtime.server) as client:
        call = asyncio.create_task(client.call_tool("wait_until_cancelled"))
        await asyncio.wait_for(started.wait(), timeout=1)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(cancelled.wait(), timeout=1)


def test_adapter_preserves_camel_case_wire_annotations() -> None:
    annotations = ToolHints(
        read_only=True,
        destructive=False,
        idempotent=True,
        open_world=False,
    ).to_mcp()

    assert annotations.model_dump(by_alias=True, exclude_none=True) == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def test_sdk_imports_are_confined_to_adapter() -> None:
    package_dir = Path(server.__file__).parent
    sdk_import = re.compile(r"^\s*(?:from|import)\s+mcp(?:\.|\s|$)", re.MULTILINE)
    offenders = [
        path.name
        for path in package_dir.glob("*.py")
        if path.name != "mcp_adapter.py" and sdk_import.search(path.read_text())
    ]

    assert offenders == []
