from __future__ import annotations

import os
import re
import subprocess
import sys
from importlib.metadata import requires, version
from pathlib import Path

EXPECTED_RUNTIME_UPPER_BOUNDS = {
    "httpx": "<1",
    "mcp": "<2",
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
