"""Exercise the privileged workflow's gate with a fake GitHub CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def eligible_pr() -> dict[str, Any]:
    return {
        "state": "OPEN",
        "isDraft": False,
        "isCrossRepository": False,
        "baseRefName": "master",
        "headRefOid": "checked-commit",
        "headRefName": "dependabot/uv/security-group",
        "author": {"login": "app/dependabot"},
        "labels": [{"name": "security"}],
    }


def run_gate(
    tmp_path: Path,
    pr: dict[str, Any],
    checks_exit: int = 0,
    check_results: list[dict[str, str]] | None = None,
) -> tuple[int, list[list[str]]]:
    yaml = pytest.importorskip("yaml")
    if shutil.which("jq") is None:
        pytest.skip("jq is required by the GitHub runner workflow")
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/auto-merge-dependencies.yml").read_text()
    )
    script = workflow["jobs"]["merge-after-ci"]["steps"][0]["run"]
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['CALLS']).open('a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:3] == ['pr', 'view']:\n"
        "    print(os.environ['PR_DATA'])\n"
        "if sys.argv[1:3] == ['pr', 'checks']:\n"
        "    if '--json' in sys.argv:\n"
        "        print(os.environ['CHECK_RESULTS'])\n"
        "    sys.exit(int(os.environ['CHECKS_EXIT']))\n"
    )
    fake_gh.chmod(0o755)
    calls_path = tmp_path / "calls.jsonl"
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PR_DATA": json.dumps(pr),
        "CALLS": str(calls_path),
        "CHECKS_EXIT": str(checks_exit),
        "CHECK_RESULTS": json.dumps(
            check_results
            if check_results is not None
            else [
                {"name": "test", "bucket": "pass"},
                {"name": "deploy", "bucket": "skipping"},
            ]
        ),
        "PR_NUMBER": "71",
        "REPO": "example/repo",
        "EXPECTED_HEAD": "checked-commit",
        "DEFAULT_BRANCH": "master",
    }
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True
    )
    return result.returncode, [
        json.loads(line) for line in calls_path.read_text().splitlines()
    ]


def test_merge_waits_for_all_checks_and_binds_commit(
    tmp_path: Path, eligible_pr: dict[str, Any]
) -> None:
    code, calls = run_gate(tmp_path, eligible_pr)
    assert code == 0
    assert [call[:2] for call in calls] == [
        ["pr", "view"],
        ["pr", "checks"],
        ["pr", "checks"],
        ["pr", "merge"],
    ]
    assert "--watch" in calls[1]
    assert "--required" not in calls[1]
    assert calls[-1][-2:] == ["--match-head-commit", "checked-commit"]


@pytest.mark.parametrize("exit_code", [1, 8])
def test_failed_or_pending_checks_never_merge(
    tmp_path: Path, eligible_pr: dict[str, Any], exit_code: int
) -> None:
    code, calls = run_gate(tmp_path, eligible_pr, exit_code)
    assert code != 0
    assert not any(call[:2] == ["pr", "merge"] for call in calls)


@pytest.mark.parametrize(
    "check_results",
    [
        [],
        [{"name": "MCP SDK (minimum)", "bucket": "cancel"}],
        [{"name": "MCP SDK (minimum)", "bucket": "skipping"}],
        [{"name": "Dependency audit", "bucket": "pending"}],
    ],
)
def test_missing_or_unvalidated_checks_never_merge(
    tmp_path: Path, eligible_pr: dict[str, Any], check_results: list[dict[str, str]]
) -> None:
    code, calls = run_gate(tmp_path, eligible_pr, check_results=check_results)
    assert code != 0
    assert not any(call[:2] == ["pr", "merge"] for call in calls)


@pytest.mark.parametrize(
    "patch",
    [
        {"headRefOid": "different-commit"},
        {"isCrossRepository": True},
        {"isDraft": True},
        {"state": "MERGED"},
        {"baseRefName": "other"},
        {"labels": [{"name": "not-security"}]},
        {"author": {"login": "untrusted-user"}},
    ],
)
def test_ineligible_pr_is_skipped(
    tmp_path: Path, eligible_pr: dict[str, Any], patch: dict[str, Any]
) -> None:
    code, calls = run_gate(tmp_path, eligible_pr | patch)
    assert code == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("branch", "label"),
    [
        ("automation/python-security", "security"),
        ("release-please--branches--master", "autorelease: pending"),
    ],
)
def test_trusted_automation_can_use_repository_update_token(
    tmp_path: Path, eligible_pr: dict[str, Any], branch: str, label: str
) -> None:
    pr = eligible_pr | {
        "headRefName": branch,
        "author": {"login": "repository-owner"},
        "labels": [{"name": label}],
    }
    code, calls = run_gate(tmp_path, pr)
    assert code == 0
    assert calls[-1][:2] == ["pr", "merge"]
