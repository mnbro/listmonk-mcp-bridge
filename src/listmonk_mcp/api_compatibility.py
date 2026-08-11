"""Runtime access to the generated Listmonk API compatibility attestation."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Any


@lru_cache(maxsize=1)
def get_api_contract_metadata() -> dict[str, Any]:
    """Load the contract metadata bundled in the installed package."""

    try:
        value = json.loads(
            files("listmonk_mcp")
            .joinpath("listmonk_api_contract.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "contractId": None,
            "upstreamDeclaredApiVersion": None,
            "sourceRelease": None,
            "sourceCommit": None,
            "verification": "unavailable",
            "compatibleListmonkReleases": [],
            "knownReleaseContracts": {},
            "error": type(exc).__name__,
        }
    if not isinstance(value, dict):
        return {
            "contractId": None,
            "verification": "unavailable",
            "compatibleListmonkReleases": [],
            "knownReleaseContracts": {},
            "error": "invalid_metadata",
        }
    return value


def expected_api_compatibility() -> dict[str, Any]:
    """Return the public, compact compatibility attestation."""

    metadata = get_api_contract_metadata()
    return {
        "contractId": metadata.get("contractId"),
        "upstreamDeclaredApiVersion": metadata.get(
            "upstreamDeclaredApiVersion"
        ),
        "sourceRelease": metadata.get("sourceRelease"),
        "sourceCommit": metadata.get("sourceCommit"),
        "verification": metadata.get("verification", "unavailable"),
        "compatibleListmonkReleases": metadata.get(
            "compatibleListmonkReleases", []
        ),
    }


def normalize_listmonk_release(value: str | None) -> str | None:
    """Extract a stable ``vMAJOR.MINOR.PATCH`` release from Listmonk output."""

    if not value:
        return None
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if match is None:
        return None
    return f"v{match.group(1)}.{match.group(2)}.{match.group(3)}"


def evaluate_listmonk_release(reported_version: str | None) -> dict[str, Any]:
    """Compare a connected Listmonk release with bundled contract evidence."""

    metadata = get_api_contract_metadata()
    normalized = normalize_listmonk_release(reported_version)
    expected_contract = metadata.get("contractId")
    compatible = metadata.get("compatibleListmonkReleases", [])
    known = metadata.get("knownReleaseContracts", {})
    detected_contract: str | None = None
    if isinstance(known, dict) and normalized is not None:
        candidate = known.get(normalized)
        if isinstance(candidate, str):
            detected_contract = candidate

    if normalized is None:
        status = "unknown"
        reason = "Listmonk did not report a stable release version."
    elif isinstance(compatible, list) and normalized in compatible:
        status = "compatible"
        reason = "The connected release maps to the bundled API contract."
    elif detected_contract is not None:
        status = "incompatible"
        reason = "The connected release maps to a different known API contract."
    else:
        status = "unknown"
        reason = "The connected release has not been classified by this bridge release."

    return {
        "reportedVersion": reported_version,
        "normalizedRelease": normalized,
        "status": status,
        "reason": reason,
        "expectedContractId": expected_contract,
        "detectedContractId": detected_contract,
    }
