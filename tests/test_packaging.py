from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib.metadata import requires, version
from pathlib import Path

EXPECTED_RUNTIME_UPPER_BOUNDS = {
    "httpx": "<1",
    "mcp": "<3",
    "pydantic": "<3",
    "pydantic-settings": "<3",
    "typer": "<1",
}


def _requirement_name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0].lower()


def test_runtime_dependencies_have_reviewed_major_version_caps() -> None:
    requirements = requires("listmonk-mcp-bridge") or []
    runtime_requirements = {
        _requirement_name(requirement): requirement
        for requirement in requirements
        if "extra ==" not in requirement
    }

    assert set(runtime_requirements) == set(EXPECTED_RUNTIME_UPPER_BOUNDS)
    for package, upper_bound in EXPECTED_RUNTIME_UPPER_BOUNDS.items():
        assert upper_bound in runtime_requirements[package].replace(" ", "")
    assert ">=2.0" in runtime_requirements["mcp"].replace(" ", "")


def test_installed_console_entry_point_reports_version() -> None:
    entry_point = Path(sys.executable).with_name("listmonk-mcp-bridge")
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "error"

    result = subprocess.run(
        [str(entry_point), "--version"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.stdout.strip() == (
        f"listmonk-mcp-bridge {version('listmonk-mcp-bridge')}"
    )
    assert result.stderr == ""


def test_installed_server_uses_public_mcp_v2_api_without_warnings() -> None:
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "error"
    code = """
import asyncio
from importlib.metadata import version
from mcp.server import MCPServer
from listmonk_mcp import server

assert version("mcp").split(".", 1)[0] == "2"
assert isinstance(server.mcp, MCPServer)
tools = asyncio.run(server.mcp.list_tools())
assert any(tool.name == "prepare_subscriber_import" for tool in tools)
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
