from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_dependencies as audit


def package(name: str, version: str, vulnerable: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "vulns": [{"id": "TEST-ADVISORY"}] if vulnerable else [],
    }


def test_audit_includes_vulnerable_variant_not_used_by_runner() -> None:
    report = {
        "dependencies": [package("AnyIO", "4.9.0", True), package("anyio", "4.15.1")]
    }
    assert audit.validate_report(
        report, {("anyio", "4.9.0"), ("anyio", "4.15.1")}, 1
    ) == {"anyio"}


def test_audit_rejects_missing_platform_variant() -> None:
    with pytest.raises(ValueError, match="Incomplete audit"):
        audit.validate_report(
            {"dependencies": [package("anyio", "4.15.1")]},
            {("anyio", "4.9.0"), ("anyio", "4.15.1")},
            0,
        )


def test_audit_rejects_skipped_dependencies() -> None:
    with pytest.raises(ValueError, match="skipped"):
        audit.validate_report(
            {
                "dependencies": [
                    {"name": "private-package", "skip_reason": "unavailable"}
                ]
            },
            {("private-package", "1.0")},
            0,
        )


def test_audit_error_is_not_a_clean_result() -> None:
    with pytest.raises(ValueError, match="exit code"):
        audit.validate_report(
            {"dependencies": [package("anyio", "4.15.1")]}, {("anyio", "4.15.1")}, 1
        )


def test_failed_audit_cannot_reuse_previous_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"dependencies": [package("anyio", "4.15.1")]}))
    monkeypatch.setattr(audit, "locked_packages", lambda root: {("anyio", "4.15.1")})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1),
    )
    with pytest.raises(FileNotFoundError):
        audit.audit(tmp_path, report)


def test_repair_reaudits_and_leaves_unfixed_vulnerabilities_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = iter([{"anyio", "gitpython"}, {"anyio"}])
    monkeypatch.setattr(audit, "audit", lambda root, report: next(results))
    commands = []
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    assert not audit.maintain(tmp_path, tmp_path / "report.json", True, False)
    assert commands == [
        ["uv", "lock", "--upgrade-package", "anyio", "--upgrade-package", "gitpython"]
    ]


def test_clean_lock_does_not_upgrade_unrelated_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "audit", lambda root, report: set())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unexpected upgrade"),
    )
    assert audit.maintain(tmp_path, tmp_path / "report.json", True, False)


def test_runtime_repair_respects_declared_project_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["mcp>=2,<3", "pydantic[email]>=2,<3", "typer>=0.26,<1"]\n'
    )
    monkeypatch.setattr(audit, "audit", lambda root, report: set())
    commands = []
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    assert audit.maintain(tmp_path, tmp_path / "report.json", True, True)
    assert commands == [
        [
            "uv",
            "lock",
            "--upgrade-package",
            "mcp",
            "--upgrade-package",
            "pydantic",
            "--upgrade-package",
            "typer",
        ]
    ]
