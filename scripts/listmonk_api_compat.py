#!/usr/bin/env python3
"""Track and validate the Listmonk API contract used by the bridge.

The upstream OpenAPI document has historically kept ``info.version`` at 1.0.0
while the API itself has changed.  This module therefore derives a stable,
content-addressed contract ID from Listmonk's registered routes, OpenAPI
document, and relevant handler-source fingerprints. It also keeps explicit
coverage decisions so new upstream routes cannot silently become MCP tools or
silently disappear from review.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_UPSTREAM_REPOSITORY = "knadh/listmonk"
ROUTER_PATH = "cmd/handlers.go"
OPENAPI_PATH = "docs/swagger/collections.yaml"
HTTP_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")
DECISION_STATUSES = {"implemented", "omitted", "review_required"}
VERIFICATION_LEVELS = {
    "runtime-certified",
    "source-verified",
    "route-compatible",
    "not-recorded",
    "incompatible",
}


class CompatibilityError(RuntimeError):
    """Raised when a compatibility artifact or upstream response is invalid."""


@dataclass(frozen=True, order=True)
class RouteKey:
    """A route identity normalized across Echo and Python f-string syntax."""

    method: str
    canonical_path: str


@dataclass(frozen=True)
class ClientCall:
    """One direct Listmonk HTTP call found in ``ListmonkClient``."""

    method: str
    path: str
    client_method: str
    transport: str

    @property
    def key(self) -> RouteKey:
        return RouteKey(self.method, canonicalize_path(self.path))


def canonical_json(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and generated files."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 hex digest."""

    return hashlib.sha256(value).hexdigest()


def canonicalize_path(path: str) -> str:
    """Normalize path parameter names without weakening path structure checks."""

    parts = []
    for part in path.split("/"):
        if part.startswith(":") or (part.startswith("{") and part.endswith("}")):
            parts.append("{}")
        else:
            parts.append(part)
    return "/".join(parts)


def route_identifier(method: str, path: str) -> str:
    """Return a human-readable exact route identifier."""

    return f"{method.upper()} {path}"


def _matching_parenthesis(source: str, opening: int) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(opening, len(source)):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise CompatibilityError("Unbalanced route registration in upstream router")


def extract_upstream_routes(router_source: str) -> list[dict[str, Any]]:
    """Extract literal ``/api`` Echo routes from Listmonk's Go router."""

    method_pattern = "|".join(HTTP_METHODS)
    pattern = re.compile(rf"\bg\.({method_pattern})\s*\(")
    routes: list[dict[str, Any]] = []
    for match in pattern.finditer(router_source):
        opening = router_source.find("(", match.start())
        closing = _matching_parenthesis(router_source, opening)
        arguments = router_source[opening + 1 : closing]
        path_match = re.match(r'\s*("(?:\\.|[^"\\])*")', arguments)
        if path_match is None:
            continue
        try:
            path = ast.literal_eval(path_match.group(1))
        except (SyntaxError, ValueError) as exc:
            raise CompatibilityError("Invalid route path literal") from exc
        if not isinstance(path, str) or not path.startswith("/api/"):
            continue
        handlers = sorted(set(re.findall(r"\ba\.([A-Z][A-Za-z0-9_]*)", arguments)))
        literals = re.findall(r'"((?:\\.|[^"\\])*)"', arguments)
        permissions = sorted(
            {
                value
                for value in literals[1:]
                if re.fullmatch(r"[a-z_]+:[a-z_]+", value)
            }
        )
        routes.append(
            {
                "method": match.group(1),
                "path": path,
                "handlers": handlers,
                "permissions": permissions,
            }
        )

    routes.sort(key=lambda route: (route["path"], route["method"]))
    seen: set[RouteKey] = set()
    for route in routes:
        key = RouteKey(route["method"], canonicalize_path(route["path"]))
        if key in seen:
            raise CompatibilityError(
                f"Duplicate canonical upstream route: {route_identifier(route['method'], route['path'])}"
            )
        seen.add(key)
    if not routes:
        raise CompatibilityError("No /api routes found in upstream router")
    return routes


def extract_declared_api_version(openapi_source: str) -> str:
    """Read ``info.version`` without adding a YAML runtime dependency."""

    info_match = re.search(r"(?m)^info:\s*$", openapi_source)
    if info_match is None:
        raise CompatibilityError("OpenAPI document has no info section")
    tail = openapi_source[info_match.end() :]
    next_section = re.search(r"(?m)^[A-Za-z][A-Za-z0-9_-]*:\s*$", tail)
    info_block = tail[: next_section.start()] if next_section else tail
    version_match = re.search(
        r'(?m)^\s+version:\s*["\']?([^"\'\s]+)["\']?\s*$', info_block
    )
    if version_match is None:
        raise CompatibilityError("OpenAPI info section has no version")
    return version_match.group(1)


def build_contract(
    *,
    upstream_repository: str,
    release: str,
    commit: str,
    release_url: str,
    router_source: str,
    openapi_source: str,
    handler_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic API contract snapshot."""

    routes = extract_upstream_routes(router_source)
    routes_sha256 = sha256_bytes(canonical_json(routes))
    openapi_sha256 = sha256_bytes(openapi_source.encode())
    handler_files: dict[str, str] = {}
    if handler_sources is not None:
        handler_names = {
            handler for route in routes for handler in route.get("handlers", [])
        }
        missing_handlers: list[str] = []
        for handler in sorted(handler_names):
            pattern = re.compile(
                rf"\bfunc\s+(?:\([^)]*\)\s*)?{re.escape(handler)}\s*\("
            )
            matching_paths = [
                path for path, source in handler_sources.items() if pattern.search(source)
            ]
            if not matching_paths:
                missing_handlers.append(handler)
            for path in matching_paths:
                handler_files[path] = sha256_bytes(handler_sources[path].encode())
        if missing_handlers:
            raise CompatibilityError(
                "Could not locate upstream handler implementations: "
                + ", ".join(missing_handlers)
            )
    handler_files_sha256 = sha256_bytes(canonical_json(handler_files))
    contract_payload = {
        "routesSha256": routes_sha256,
        "openapiSha256": openapi_sha256,
        "handlerFilesSha256": handler_files_sha256,
    }
    contract_sha256 = sha256_bytes(canonical_json(contract_payload))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractId": f"lm-api:sha256:{contract_sha256}",
        "upstreamDeclaredApiVersion": extract_declared_api_version(openapi_source),
        "source": {
            "repository": upstream_repository,
            "release": release,
            "commit": commit,
            "releaseUrl": release_url,
            "routerPath": ROUTER_PATH,
            "openapiPath": OPENAPI_PATH,
        },
        "fingerprints": contract_payload,
        "handlerFiles": dict(sorted(handler_files.items())),
        "routes": routes,
    }


def _fstring_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append("{}")
        else:
            return None
    return "".join(parts)


def extract_client_calls(client_source: str) -> list[ClientCall]:
    """Extract direct HTTP calls from methods on ``ListmonkClient``."""

    tree = ast.parse(client_source)
    client_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ListmonkClient"
        ),
        None,
    )
    if client_class is None:
        raise CompatibilityError("ListmonkClient class was not found")

    transports = {
        "_request": "json",
        "_request_form": "form",
        "_request_files": "multipart",
    }
    calls: set[ClientCall] = set()
    for function in client_class.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            transport = transports.get(node.func.attr)
            if transport is None or len(node.args) < 2:
                continue
            method_node, path_node = node.args[:2]
            if not (
                isinstance(method_node, ast.Constant)
                and isinstance(method_node.value, str)
            ):
                continue
            path = _fstring_path(path_node)
            method = method_node.value.upper()
            if path is None or not path.startswith("/api/") or method not in HTTP_METHODS:
                continue
            calls.add(ClientCall(method, path, function.name, transport))
    if not calls:
        raise CompatibilityError("No direct Listmonk client calls were found")
    return sorted(calls, key=lambda call: (call.path, call.method, call.client_method))


def extract_mcp_surfaces(
    server_source: str, client_methods: Iterable[str]
) -> dict[str, list[str]]:
    """Map direct client method use to registered MCP tools and resources."""

    known_methods = set(client_methods)
    tree = ast.parse(server_source)
    surfaces: dict[str, set[str]] = defaultdict(set)
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        surface: str | None = None
        for decorator in function.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call is not None else decorator
            if not isinstance(target, ast.Name):
                continue
            if target.id == "listmonk_tool":
                surface = f"tool:{function.name}"
                break
            if target.id == "listmonk_resource":
                resource = None
                if call is not None and call.args:
                    candidate = call.args[0]
                    if isinstance(candidate, ast.Constant) and isinstance(
                        candidate.value, str
                    ):
                        resource = candidate.value
                surface = f"resource:{resource or function.name}"
                break
        if surface is None:
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in known_methods
            ):
                surfaces[node.func.attr].add(surface)
    return {
        method: sorted(values) for method, values in sorted(surfaces.items())
    }


def _route_maps(
    contract: dict[str, Any], calls: Sequence[ClientCall]
) -> tuple[dict[RouteKey, dict[str, Any]], dict[RouteKey, list[ClientCall]]]:
    upstream: dict[RouteKey, dict[str, Any]] = {}
    for route in contract["routes"]:
        key = RouteKey(route["method"], canonicalize_path(route["path"]))
        upstream[key] = route
    usage: dict[RouteKey, list[ClientCall]] = defaultdict(list)
    for call in calls:
        usage[call.key].append(call)
    return upstream, dict(usage)


def update_policy(
    contract: dict[str, Any],
    calls: Sequence[ClientCall],
    existing: dict[str, Any] | None,
    *,
    bootstrap: bool = False,
    mcp_surfaces: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Carry explicit decisions forward and flag every unseen route for review."""

    upstream, usage = _route_maps(contract, calls)
    old_decisions: dict[tuple[str, str], dict[str, Any]] = {}
    if existing:
        for old_decision in existing.get("decisions", []):
            old_decisions[
                (old_decision["method"], old_decision["path"])
            ] = old_decision

    decisions: list[dict[str, Any]] = []
    source_release = contract["source"]["release"]
    for key, route in sorted(upstream.items(), key=lambda item: (item[1]["path"], item[1]["method"])):
        exact_key = (route["method"], route["path"])
        old = old_decisions.get(exact_key)
        route_calls = usage.get(key, [])
        methods = sorted({call.client_method for call in route_calls})
        transports = sorted({call.transport for call in route_calls})
        route_surfaces = sorted(
            {
                surface
                for method in methods
                for surface in (mcp_surfaces or {}).get(method, [])
            }
        )

        if bootstrap:
            if route_calls:
                status = "implemented"
                reason = "Directly used by the Listmonk client."
            else:
                status = "omitted"
                reason = (
                    f"Reviewed against {source_release}; not exposed by the current bridge scope."
                )
        elif old is None:
            status = "review_required"
            reason = f"New in {source_release}; implementation or explicit omission required."
        else:
            status = old.get("status", "review_required")
            reason = old.get("reason", "")
            if status == "implemented" and not route_calls:
                status = "review_required"
                reason = "Previously implemented route is no longer called by the client."
            elif status == "omitted" and route_calls:
                status = "review_required"
                reason = "Client now calls a route that was explicitly omitted."

        decision: dict[str, Any] = {
            "method": route["method"],
            "path": route["path"],
            "status": status,
            "reason": reason,
        }
        if methods:
            decision["clientMethods"] = methods
            decision["transports"] = transports
        if route_surfaces:
            decision["mcpSurfaces"] = route_surfaces
        decisions.append(decision)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractId": contract["contractId"],
        "reviewedContractId": (
            contract["contractId"]
            if bootstrap
            else (existing or {}).get("reviewedContractId")
        ),
        "decisions": decisions,
    }


def update_upstream_ledger(
    ledger: dict[str, Any] | None, contract: dict[str, Any]
) -> dict[str, Any]:
    """Record the contract observed for an exact Listmonk release."""

    releases = {
        entry["release"]: entry
        for entry in (ledger or {}).get("releases", [])
        if isinstance(entry, dict) and isinstance(entry.get("release"), str)
    }
    source = contract["source"]
    releases[source["release"]] = {
        "release": source["release"],
        "commit": source["commit"],
        "contractId": contract["contractId"],
        "upstreamDeclaredApiVersion": contract["upstreamDeclaredApiVersion"],
        "releaseUrl": source["releaseUrl"],
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "releases": sorted(
            releases.values(), key=lambda item: version_key(item["release"])
        ),
    }


def runtime_metadata(
    contract: dict[str, Any], ledger: dict[str, Any], verification: str
) -> dict[str, Any]:
    """Build compact package metadata used by the capability report."""

    if verification not in VERIFICATION_LEVELS:
        raise CompatibilityError(f"Unknown verification level: {verification}")
    known: dict[str, str] = {
        entry["release"]: entry["contractId"] for entry in ledger["releases"]
    }
    compatible = sorted(
        [release for release, contract_id in known.items() if contract_id == contract["contractId"]],
        key=version_key,
    )
    source = contract["source"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractId": contract["contractId"],
        "upstreamDeclaredApiVersion": contract["upstreamDeclaredApiVersion"],
        "sourceRelease": source["release"],
        "sourceCommit": source["commit"],
        "verification": verification,
        "compatibleListmonkReleases": compatible,
        "knownReleaseContracts": dict(sorted(known.items(), key=lambda item: version_key(item[0]))),
    }


def version_key(value: str) -> tuple[int, ...]:
    """Return a deterministic numeric key for project release strings."""

    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return (-1,)
    return tuple(int(part) for part in match.groups())


def normalize_bridge_release(value: str) -> str:
    """Normalize and validate a bridge release tag."""

    normalized = value if value.startswith("v") else f"v{value}"
    if version_key(normalized) == (-1,):
        raise CompatibilityError(f"Invalid bridge release: {value}")
    return normalized


def discover_bridge_releases(repo_root: Path) -> list[str]:
    """Discover released versions from the changelog and current project metadata."""

    releases: set[str] = set()
    changelog = (repo_root / "CHANGELOG.md").read_text()
    releases.update(
        normalize_bridge_release(value)
        for value in re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\]", changelog)
    )
    pyproject = (repo_root / "pyproject.toml").read_text()
    version_match = re.search(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', pyproject)
    if version_match:
        releases.add(normalize_bridge_release(version_match.group(1)))
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pass
    else:
        for value in result.stdout.splitlines():
            if version_key(value) != (-1,):
                releases.add(normalize_bridge_release(value))
    return sorted(releases, key=version_key)


def backfill_unknown_releases(
    matrix: dict[str, Any] | None, releases: Iterable[str]
) -> dict[str, Any]:
    """Represent historical releases without inventing compatibility evidence."""

    entries = {
        entry["bridgeRelease"]: entry
        for entry in (matrix or {}).get("releases", [])
        if isinstance(entry, dict) and isinstance(entry.get("bridgeRelease"), str)
    }
    for release in releases:
        entries.setdefault(
            release,
            {
                "bridgeRelease": release,
                "apiContractId": None,
                "sourceRelease": None,
                "upstreamDeclaredApiVersion": None,
                "verification": "not-recorded",
            },
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "releases": sorted(
            entries.values(), key=lambda item: version_key(item["bridgeRelease"])
        ),
    }


def stamp_bridge_release(
    matrix: dict[str, Any],
    contract: dict[str, Any],
    bridge_release: str,
    verification: str,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Bind one bridge release to the current exact API contract."""

    if verification not in VERIFICATION_LEVELS - {"not-recorded"}:
        raise CompatibilityError(f"Invalid attested verification level: {verification}")
    release = normalize_bridge_release(bridge_release)
    entries = {
        entry["bridgeRelease"]: entry for entry in matrix.get("releases", [])
    }
    existing = entries.get(release)
    if (
        existing
        and existing.get("apiContractId")
        and existing["apiContractId"] != contract["contractId"]
        and not replace
    ):
        raise CompatibilityError(
            f"{release} is already bound to a different API contract"
        )
    entries[release] = {
        "bridgeRelease": release,
        "apiContractId": contract["contractId"],
        "sourceRelease": contract["source"]["release"],
        "sourceCommit": contract["source"]["commit"],
        "upstreamDeclaredApiVersion": contract["upstreamDeclaredApiVersion"],
        "verification": verification,
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "releases": sorted(
            entries.values(), key=lambda item: version_key(item["bridgeRelease"])
        ),
    }


def short_contract_id(contract_id: str | None) -> str:
    """Return a readable contract link label."""

    if not contract_id:
        return "—"
    return f"`lm-api:{contract_id.rsplit(':', 1)[-1][:12]}`"


def render_compatibility_docs(
    contract: dict[str, Any],
    ledger: dict[str, Any],
    matrix: dict[str, Any],
    policy: dict[str, Any],
) -> str:
    """Render the human-readable compatibility matrix."""

    source = contract["source"]
    decisions = policy["decisions"]
    implemented = sum(item["status"] == "implemented" for item in decisions)
    omitted = sum(item["status"] == "omitted" for item in decisions)
    pending = sum(item["status"] == "review_required" for item in decisions)
    compatible_sources = [
        entry["release"]
        for entry in ledger["releases"]
        if entry["contractId"] == contract["contractId"]
    ]

    lines = [
        "# Listmonk API Compatibility",
        "",
        "Listmonk currently declares OpenAPI version `1.0.0`, but that value does",
        "not change for every upstream API change. The bridge therefore identifies",
        "the API by a content-addressed contract derived from registered routes,",
        "permissions, the upstream OpenAPI document and relevant Go handler-source",
        "fingerprints.",
        "",
        "## Current Development Contract",
        "",
        f"- Contract: `{contract['contractId']}`",
        f"- Upstream-declared API version: `{contract['upstreamDeclaredApiVersion']}`",
        f"- Source snapshot: [{source['release']}]({source['releaseUrl']}) at `{source['commit']}`",
        f"- Known Listmonk releases with this contract: {', '.join(f'`{item}`' for item in compatible_sources)}",
        f"- Route decisions: {implemented} implemented, {omitted} intentionally omitted, {pending} awaiting review",
        "",
        "## Bridge Release Matrix",
        "",
        "| Bridge release | API contract | Source snapshot | Verification |",
        "| --- | --- | --- | --- |",
    ]
    for entry in sorted(
        matrix["releases"],
        key=lambda item: version_key(item["bridgeRelease"]),
        reverse=True,
    ):
        bridge_release = entry["bridgeRelease"]
        release_link = (
            f"[`{bridge_release}`](https://github.com/mnbro/listmonk-mcp-bridge/releases/tag/{bridge_release})"
        )
        source_release = entry.get("sourceRelease")
        source_cell = (
            f"[`{source_release}`](https://github.com/knadh/listmonk/releases/tag/{source_release})"
            if source_release
            else "—"
        )
        lines.append(
            f"| {release_link} | {short_contract_id(entry.get('apiContractId'))} | "
            f"{source_cell} | `{entry['verification']}` |"
        )
    lines.extend(
        [
            "",
            "## Verification Levels",
            "",
            "- `runtime-certified`: passed the disposable Listmonk integration suite.",
            "- `source-verified`: routes, schemas and relevant behavior were audited against the named source snapshot.",
            "- `route-compatible`: method and path compatibility was checked statically.",
            "- `not-recorded`: the historical release predates compatibility attestations.",
            "- `incompatible`: a known contract conflict prevents supported operation.",
            "",
            "Historical entries remain `not-recorded` unless reproducible evidence is",
            "available. The automation never infers semantic compatibility from dates or",
            "release numbers alone.",
            "",
            "Machine-readable records are stored in",
            "[`compatibility/listmonk-api-contract.json`](https://github.com/mnbro/listmonk-mcp-bridge/blob/master/compatibility/listmonk-api-contract.json)",
            "and",
            "[`compatibility/bridge-releases.json`](https://github.com/mnbro/listmonk-mcp-bridge/blob/master/compatibility/bridge-releases.json).",
            "",
        ]
    )
    return "\n".join(lines)


def read_json(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    """Read a JSON object from disk."""

    if optional and not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write a deterministic generated JSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


class GitHubSource:
    """Minimal GitHub API reader for public upstream release artifacts."""

    def __init__(self, repository: str, token: str | None = None) -> None:
        self.repository = repository
        self.token = token

    def _get_json(self, path: str) -> dict[str, Any]:
        try:
            value = json.loads(self._get_bytes(path))
        except json.JSONDecodeError as exc:
            raise CompatibilityError(
                f"Invalid GitHub API JSON for https://api.github.com{path}"
            ) from exc
        if not isinstance(value, dict):
            raise CompatibilityError(
                f"Unexpected GitHub API response for https://api.github.com{path}"
            )
        return value

    def _get_bytes(self, path: str) -> bytes:
        url = f"https://api.github.com{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "listmonk-mcp-bridge-api-watch",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except urllib.error.URLError as exc:
            raise CompatibilityError(f"GitHub API request failed for {url}: {exc}") from exc
        if not isinstance(payload, bytes):
            raise CompatibilityError(f"Unexpected binary response for {url}")
        return payload

    def resolve_release(self, tag: str) -> dict[str, str]:
        endpoint = (
            f"/repos/{self.repository}/releases/latest"
            if tag == "latest"
            else f"/repos/{self.repository}/releases/tags/{urllib.parse.quote(tag, safe='')}"
        )
        release = self._get_json(endpoint)
        resolved_tag = release.get("tag_name")
        if not isinstance(resolved_tag, str) or not re.fullmatch(
            r"v\d+\.\d+\.\d+", resolved_tag
        ):
            raise CompatibilityError(
                f"Refusing non-stable Listmonk release tag: {resolved_tag!r}"
            )
        commit = self._get_json(
            f"/repos/{self.repository}/commits/{urllib.parse.quote(resolved_tag, safe='')}"
        ).get("sha")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise CompatibilityError(f"Could not resolve commit for {resolved_tag}")
        html_url = release.get("html_url")
        if not isinstance(html_url, str):
            html_url = f"https://github.com/{self.repository}/releases/tag/{resolved_tag}"
        return {"tag": resolved_tag, "commit": commit, "url": html_url}

    def content(self, path: str, ref: str) -> str:
        encoded_path = urllib.parse.quote(path, safe="/")
        encoded_ref = urllib.parse.quote(ref, safe="")
        response = self._get_json(
            f"/repos/{self.repository}/contents/{encoded_path}?ref={encoded_ref}"
        )
        encoded = response.get("content")
        if not isinstance(encoded, str):
            raise CompatibilityError(f"No content returned for {path}@{ref}")
        try:
            return base64.b64decode(encoded).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise CompatibilityError(f"Invalid content returned for {path}@{ref}") from exc

    def command_sources(self, ref: str) -> dict[str, str]:
        """Read Go sources from an upstream release archive without extracting it."""

        encoded_ref = urllib.parse.quote(ref, safe="")
        archive = self._get_bytes(f"/repos/{self.repository}/tarball/{encoded_ref}")
        sources: dict[str, str] = {}
        total_size = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as handle:
                for member in handle.getmembers():
                    parts = Path(member.name).parts
                    if (
                        not member.isfile()
                        or len(parts) != 3
                        or parts[1] != "cmd"
                        or not parts[2].endswith(".go")
                    ):
                        continue
                    if member.size > 2_000_000:
                        raise CompatibilityError(
                            f"Refusing unexpectedly large upstream file: {member.name}"
                        )
                    total_size += member.size
                    if total_size > 25_000_000:
                        raise CompatibilityError("Upstream command sources exceed size limit")
                    extracted = handle.extractfile(member)
                    if extracted is None:
                        raise CompatibilityError(f"Cannot read {member.name} from archive")
                    sources[f"cmd/{parts[2]}"] = extracted.read().decode()
        except (tarfile.TarError, UnicodeDecodeError) as exc:
            raise CompatibilityError("Invalid upstream source archive") from exc
        if not sources:
            raise CompatibilityError("No cmd/*.go files found in upstream source archive")
        return sources


def artifact_paths(repo_root: Path) -> dict[str, Path]:
    """Return every generated compatibility artifact path."""

    return {
        "contract": repo_root / "compatibility/listmonk-api-contract.json",
        "policy": repo_root / "compatibility/listmonk-api-policy.json",
        "ledger": repo_root / "compatibility/listmonk-upstream-releases.json",
        "matrix": repo_root / "compatibility/bridge-releases.json",
        "runtime": repo_root / "src/listmonk_mcp/listmonk_api_contract.json",
        "docs": repo_root / "docs/compatibility.md",
    }


def validation_errors(repo_root: Path) -> tuple[list[str], dict[str, int]]:
    """Validate local source and every tracked compatibility artifact."""

    paths = artifact_paths(repo_root)
    contract = read_json(paths["contract"])
    policy = read_json(paths["policy"])
    ledger = read_json(paths["ledger"])
    matrix = read_json(paths["matrix"])
    runtime = read_json(paths["runtime"])
    assert contract is not None
    assert policy is not None
    assert ledger is not None
    assert matrix is not None
    assert runtime is not None
    calls = extract_client_calls((repo_root / "src/listmonk_mcp/client.py").read_text())
    mcp_surfaces = extract_mcp_surfaces(
        (repo_root / "src/listmonk_mcp/server.py").read_text(),
        (call.client_method for call in calls),
    )
    upstream, usage = _route_maps(contract, calls)
    errors: list[str] = []

    if policy.get("contractId") != contract.get("contractId"):
        errors.append("policy contractId does not match the current contract")
    if policy.get("reviewedContractId") != contract.get("contractId"):
        errors.append(
            "current API contract has not been explicitly reviewed and acknowledged"
        )
    decisions = policy.get("decisions")
    if not isinstance(decisions, list):
        errors.append("policy decisions must be a list")
        decisions = []
    decision_map: dict[RouteKey, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append("policy contains a non-object decision")
            continue
        status = decision.get("status")
        if status not in DECISION_STATUSES:
            errors.append(
                f"invalid status for {decision.get('method')} {decision.get('path')}: {status}"
            )
            continue
        key = RouteKey(
            str(decision.get("method")), canonicalize_path(str(decision.get("path")))
        )
        if key in decision_map:
            errors.append(
                f"duplicate policy decision: {decision.get('method')} {decision.get('path')}"
            )
        decision_map[key] = decision
        if status == "review_required":
            errors.append(
                f"review required: {decision.get('method')} {decision.get('path')}"
            )
        if not str(decision.get("reason", "")).strip():
            errors.append(
                f"missing policy reason: {decision.get('method')} {decision.get('path')}"
            )

    for key, route in upstream.items():
        decision = decision_map.get(key)
        if decision is None:
            errors.append(f"unclassified upstream route: {route_identifier(route['method'], route['path'])}")
            continue
        route_calls = usage.get(key, [])
        if decision["status"] == "implemented" and not route_calls:
            errors.append(f"implemented route has no client call: {route_identifier(route['method'], route['path'])}")
        if decision["status"] == "omitted" and route_calls:
            errors.append(f"omitted route is called by the client: {route_identifier(route['method'], route['path'])}")
        expected_methods = sorted({call.client_method for call in route_calls})
        if route_calls and decision.get("clientMethods") != expected_methods:
            errors.append(f"client method mapping is stale: {route_identifier(route['method'], route['path'])}")
        expected_surfaces = sorted(
            {
                surface
                for method in expected_methods
                for surface in mcp_surfaces.get(method, [])
            }
        )
        if expected_surfaces and decision.get("mcpSurfaces") != expected_surfaces:
            errors.append(f"MCP surface mapping is stale: {route_identifier(route['method'], route['path'])}")
        if not expected_surfaces and decision.get("mcpSurfaces"):
            errors.append(f"MCP surface mapping is stale: {route_identifier(route['method'], route['path'])}")

    for key, route_calls in usage.items():
        if key not in upstream:
            for call in route_calls:
                errors.append(
                    f"bridge route is absent upstream: {route_identifier(call.method, call.path)} ({call.client_method})"
                )

    for key, decision in decision_map.items():
        if key not in upstream:
            errors.append(
                f"policy route is absent from current contract: {decision['method']} {decision['path']}"
            )

    expected_runtime = runtime_metadata(
        contract, ledger, str(runtime.get("verification", "source-verified"))
    )
    if runtime != expected_runtime:
        errors.append("packaged runtime API contract metadata is stale")
    expected_docs = render_compatibility_docs(contract, ledger, matrix, policy)
    if not paths["docs"].exists() or paths["docs"].read_text() != expected_docs:
        errors.append("generated compatibility documentation is stale")

    counts = {
        "upstreamRoutes": len(upstream),
        "clientCalls": len(calls),
        "implementedRoutes": sum(
            decision.get("status") == "implemented" for decision in decisions
        ),
        "omittedRoutes": sum(decision.get("status") == "omitted" for decision in decisions),
        "reviewRequiredRoutes": sum(
            decision.get("status") == "review_required" for decision in decisions
        ),
    }
    return errors, counts


def write_github_output(path: Path, summary: dict[str, Any]) -> None:
    """Append scalar scan results to a GitHub Actions output file."""

    with path.open("a") as handle:
        for key, value in summary.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, (str, int)):
                rendered = str(value)
            else:
                continue
            handle.write(f"{key}={rendered}\n")


def render_scan_report(
    *,
    previous: dict[str, Any] | None,
    contract: dict[str, Any],
    policy: dict[str, Any],
    missing_bridge_routes: Sequence[str],
    contract_changed: bool,
) -> str:
    """Render a bounded review report for the automation PR or issue."""

    previous_routes = {
        route_identifier(route["method"], route["path"])
        for route in (previous or {}).get("routes", [])
    }
    current_routes = {
        route_identifier(route["method"], route["path"])
        for route in contract["routes"]
    }
    added = sorted(current_routes - previous_routes)
    removed = sorted(previous_routes - current_routes)
    pending = [
        route_identifier(item["method"], item["path"])
        for item in policy["decisions"]
        if item["status"] == "review_required"
    ]
    source = contract["source"]
    lines = [
        f"# Listmonk API scan: {source['release']}",
        "",
        f"- Source commit: `{source['commit']}`",
        f"- API contract: `{contract['contractId']}`",
        f"- Upstream-declared API version: `{contract['upstreamDeclaredApiVersion']}`",
        f"- Registered API routes: {len(contract['routes'])}",
        "",
        "## Route changes",
        "",
    ]
    if not added and not removed:
        lines.append("No method/path changes were detected.")
    if added:
        lines.extend(["Added:", "", *[f"- `{item}`" for item in added]])
    if removed:
        lines.extend(["", "Removed:", "", *[f"- `{item}`" for item in removed]])
    lines.extend(["", "## Required review", ""])
    if contract_changed:
        lines.append(
            "- The route, schema, permission, or relevant handler-source fingerprint changed."
        )
    if pending:
        lines.extend(f"- `{item}`" for item in pending)
    if missing_bridge_routes:
        lines.extend(f"- Bridge call missing upstream: `{item}`" for item in missing_bridge_routes)
    if not contract_changed and not pending and not missing_bridge_routes:
        lines.append("No unresolved coverage decisions or broken bridge routes were detected.")
    lines.extend(
        [
            "",
            "The generated contract is data only. Upstream code was not executed.",
            "CI must pass before this compatibility update can merge.",
            "",
        ]
    )
    return "\n".join(lines)


def command_scan(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    paths = artifact_paths(repo_root)
    previous = read_json(paths["contract"], optional=True)
    existing_policy = read_json(paths["policy"], optional=True)
    ledger = read_json(paths["ledger"], optional=True)
    matrix = read_json(paths["matrix"], optional=True)

    source = GitHubSource(args.upstream_repository, os.environ.get("GITHUB_TOKEN"))
    release = source.resolve_release(args.tag)
    router = source.content(ROUTER_PATH, release["tag"])
    openapi = source.content(OPENAPI_PATH, release["tag"])
    handler_sources = source.command_sources(release["tag"])
    contract = build_contract(
        upstream_repository=args.upstream_repository,
        release=release["tag"],
        commit=release["commit"],
        release_url=release["url"],
        router_source=router,
        openapi_source=openapi,
        handler_sources=handler_sources,
    )
    calls = extract_client_calls((repo_root / "src/listmonk_mcp/client.py").read_text())
    mcp_surfaces = extract_mcp_surfaces(
        (repo_root / "src/listmonk_mcp/server.py").read_text(),
        (call.client_method for call in calls),
    )
    policy = update_policy(
        contract,
        calls,
        existing_policy,
        bootstrap=args.bootstrap_policy,
        mcp_surfaces=mcp_surfaces,
    )
    updated_ledger = update_upstream_ledger(ledger, contract)
    updated_matrix = backfill_unknown_releases(
        matrix, discover_bridge_releases(repo_root)
    )
    if args.stamp_version:
        updated_matrix = stamp_bridge_release(
            updated_matrix,
            contract,
            args.stamp_version,
            args.verification,
            replace=args.bootstrap_policy,
        )
    runtime = runtime_metadata(contract, updated_ledger, args.verification)
    docs = render_compatibility_docs(contract, updated_ledger, updated_matrix, policy)

    upstream, usage = _route_maps(contract, calls)
    missing_bridge_routes = sorted(
        route_identifier(call.method, call.path)
        for key, route_calls in usage.items()
        if key not in upstream
        for call in route_calls
    )
    review_required = sum(
        decision["status"] == "review_required" for decision in policy["decisions"]
    )
    contract_changed = bool(
        previous and previous.get("contractId") != contract.get("contractId")
    )
    release_changed = bool(
        not previous
        or previous.get("source", {}).get("release") != release["tag"]
        or previous.get("source", {}).get("commit") != release["commit"]
    )

    if args.write:
        write_json(paths["contract"], contract)
        write_json(paths["policy"], policy)
        write_json(paths["ledger"], updated_ledger)
        write_json(paths["matrix"], updated_matrix)
        write_json(paths["runtime"], runtime)
        paths["docs"].parent.mkdir(parents=True, exist_ok=True)
        paths["docs"].write_text(docs)
    report = render_scan_report(
        previous=previous,
        contract=contract,
        policy=policy,
        missing_bridge_routes=missing_bridge_routes,
        contract_changed=contract_changed,
    )
    if args.report:
        Path(args.report).write_text(report)

    summary = {
        "release": release["tag"],
        "commit": release["commit"],
        "contract_id": contract["contractId"],
        "contract_changed": contract_changed,
        "release_changed": release_changed,
        "review_required": review_required,
        "missing_bridge_routes": len(missing_bridge_routes),
        "needs_attention": bool(
            contract_changed or review_required or missing_bridge_routes
        ),
    }
    if args.github_output:
        write_github_output(Path(args.github_output), summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    errors, counts = validation_errors(Path(args.repo_root).resolve())
    print(json.dumps(counts, sort_keys=True))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


def command_stamp_release(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    paths = artifact_paths(repo_root)
    contract = read_json(paths["contract"])
    policy = read_json(paths["policy"])
    ledger = read_json(paths["ledger"])
    matrix = read_json(paths["matrix"], optional=True)
    assert contract is not None
    assert policy is not None
    assert ledger is not None
    updated = backfill_unknown_releases(matrix, discover_bridge_releases(repo_root))
    updated = stamp_bridge_release(
        updated, contract, args.version, args.verification
    )
    docs = render_compatibility_docs(contract, ledger, updated, policy)
    if args.write:
        write_json(paths["matrix"], updated)
        paths["docs"].write_text(docs)
    else:
        print(json.dumps(updated, indent=2))
    return 0


def command_acknowledge(args: argparse.Namespace) -> int:
    """Acknowledge a reviewed contract after all route decisions are resolved."""

    repo_root = Path(args.repo_root).resolve()
    paths = artifact_paths(repo_root)
    contract = read_json(paths["contract"])
    policy = read_json(paths["policy"])
    assert contract is not None
    assert policy is not None
    pending = [
        decision
        for decision in policy.get("decisions", [])
        if decision.get("status") == "review_required"
    ]
    if pending:
        raise CompatibilityError(
            f"Cannot acknowledge a contract with {len(pending)} review-required routes"
        )
    calls = extract_client_calls((repo_root / "src/listmonk_mcp/client.py").read_text())
    upstream, usage = _route_maps(contract, calls)
    missing = [call for key, values in usage.items() if key not in upstream for call in values]
    if missing:
        raise CompatibilityError(
            "Cannot acknowledge bridge calls absent from upstream: "
            + ", ".join(route_identifier(call.method, call.path) for call in missing)
        )
    policy["reviewedContractId"] = contract["contractId"]
    if args.write:
        write_json(paths["policy"], policy)
    else:
        print(contract["contractId"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Fetch and record an upstream release")
    scan.add_argument("--tag", default="latest")
    scan.add_argument("--upstream-repository", default=DEFAULT_UPSTREAM_REPOSITORY)
    scan.add_argument("--write", action="store_true")
    scan.add_argument("--bootstrap-policy", action="store_true")
    scan.add_argument("--stamp-version")
    scan.add_argument(
        "--verification", choices=sorted(VERIFICATION_LEVELS), default="source-verified"
    )
    scan.add_argument("--report")
    scan.add_argument("--github-output")
    scan.set_defaults(func=command_scan)

    validate = subparsers.add_parser(
        "validate", help="Validate local compatibility artifacts"
    )
    validate.set_defaults(func=command_validate)

    stamp = subparsers.add_parser(
        "stamp-release", help="Bind a bridge release to the current contract"
    )
    stamp.add_argument("--version", required=True)
    stamp.add_argument(
        "--verification", choices=sorted(VERIFICATION_LEVELS), default="source-verified"
    )
    stamp.add_argument("--write", action="store_true")
    stamp.set_defaults(func=command_stamp_release)

    acknowledge = subparsers.add_parser(
        "acknowledge", help="Record explicit review of the current contract"
    )
    acknowledge.add_argument("--write", action="store_true")
    acknowledge.set_defaults(func=command_acknowledge)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CompatibilityError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
