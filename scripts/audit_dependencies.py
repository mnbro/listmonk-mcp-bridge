"""Audit every locked package variant and optionally refresh affected dependencies."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = "pip-audit==2.10.1"


def canonical_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError(f"Invalid dependency name: {name!r}")
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(root: Path) -> set[tuple[str, str]]:
    with (root / "uv.lock").open("rb") as stream:
        packages = tomllib.load(stream)["package"]
    result = set()
    for package in packages:
        if package["source"].get("editable") == ".":
            continue
        if "registry" not in package["source"]:
            raise ValueError(f"Cannot audit non-registry dependency {package['name']}")
        result.add((canonical_name(package["name"]), package["version"]))
    if not result:
        raise ValueError("No locked dependencies found")
    return result


def validate_report(
    report: dict[str, Any], expected: set[tuple[str, str]], returncode: int
) -> set[str]:
    """Reject incomplete audits, including skipped packages and platform variants."""
    observed = set()
    vulnerable = set()
    for dependency in report["dependencies"]:
        if "skip_reason" in dependency:
            raise ValueError(f"Audit skipped {dependency['name']}")
        name = canonical_name(dependency["name"])
        observed.add((name, dependency["version"]))
        if dependency["vulns"]:
            vulnerable.add(name)
    if observed != expected:
        raise ValueError(
            f"Incomplete audit: missing={expected - observed}, unexpected={observed - expected}"
        )
    if returncode != (1 if vulnerable else 0):
        raise ValueError(f"Auditor failed with exit code {returncode}")
    return vulnerable


def audit(root: Path, report_path: Path) -> set[str]:
    expected = locked_packages(root)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="listmonk-audit-") as directory:
        # PEP 751 preserves every Python/platform variant. pip-audit reads all of
        # them without installing packages or filtering to the runner's platform.
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--all-extras",
                "--no-emit-project",
                "--format",
                "pylock.toml",
                "--output-file",
                str(Path(directory) / "pylock.toml"),
                "--quiet",
            ],
            cwd=root,
            check=True,
        )
        result = subprocess.run(
            [
                "uvx",
                "--from",
                AUDITOR,
                "pip-audit",
                "--locked",
                directory,
                "--strict",
                "--progress-spinner",
                "off",
                "--format",
                "json",
                "--output",
                str(report_path),
            ],
            cwd=root,
            check=False,
        )
    report = json.loads(report_path.read_text())
    vulnerable = validate_report(report, expected, result.returncode)
    print(
        f"Audited {len(expected)} locked package versions; vulnerable: {sorted(vulnerable)}"
    )
    return vulnerable


def runtime_packages(root: Path) -> set[str]:
    with (root / "pyproject.toml").open("rb") as stream:
        requirements = tomllib.load(stream)["project"]["dependencies"]
    return {
        canonical_name(re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0])
        for requirement in requirements
    }


def maintain(root: Path, report_path: Path, fix: bool, refresh_runtime: bool) -> bool:
    vulnerable = audit(root, report_path)
    if fix:
        targets = vulnerable | (runtime_packages(root) if refresh_runtime else set())
        if targets:
            command = ["uv", "lock"]
            for name in sorted(targets):
                command.extend(["--upgrade-package", name])
            # The resolver must respect pyproject.toml bounds. Never widen them.
            subprocess.run(command, cwd=root, check=True)
            vulnerable = audit(root, report_path)
    if vulnerable:
        print(
            "Dependencies still need review: " + ", ".join(sorted(vulnerable)),
            file=sys.stderr,
        )
    return not vulnerable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--refresh-runtime", action="store_true")
    args = parser.parse_args()
    if args.refresh_runtime and not args.fix:
        parser.error("--refresh-runtime requires --fix")
    try:
        clean = maintain(ROOT, args.report.resolve(), args.fix, args.refresh_runtime)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Dependency audit failed: {error}", file=sys.stderr)
        return 2
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write(
                "\nDependency audit: "
                + (
                    "no known vulnerabilities in any locked variant."
                    if clean
                    else "review required."
                )
                + "\n"
            )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
