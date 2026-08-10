from __future__ import annotations

import subprocess
import sys
from importlib.metadata import requires, version
from pathlib import Path


def test_mcp_dependency_excludes_breaking_v2() -> None:
    requirements = requires("listmonk-mcp-bridge") or []
    mcp_requirements = [
        requirement
        for requirement in requirements
        if requirement.partition(";")[0].strip().startswith("mcp")
    ]

    assert len(mcp_requirements) == 1
    assert "<2" in mcp_requirements[0].replace(" ", "")


def test_installed_console_entry_point_reports_version() -> None:
    entry_point = Path(sys.executable).with_name("listmonk-mcp-bridge")

    result = subprocess.run(
        [str(entry_point), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == (
        f"listmonk-mcp-bridge {version('listmonk-mcp-bridge')}"
    )
