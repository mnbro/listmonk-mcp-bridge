from __future__ import annotations

import json
from pathlib import Path

import pytest

from listmonk_mcp import api_compatibility
from scripts.listmonk_api_compat import (
    backfill_unknown_releases,
    build_contract,
    discover_bridge_releases,
    extract_client_calls,
    extract_mcp_surfaces,
    extract_upstream_routes,
    stamp_bridge_release,
    update_policy,
    validation_errors,
)

ROOT = Path(__file__).resolve().parents[1]


def sample_openapi() -> str:
    return """\
openapi: 3.0.0
info:
  version: "1.0.0"
  title: Listmonk
paths: {}
"""


def sample_router(*, include_new: bool = False) -> str:
    new_route = 'g.POST("/api/items", pm(a.CreateItem, "items:manage"))' if include_new else ""
    return f"""\
g.GET("/api/health", a.HealthCheck)
g.PUT("/api/items/:id", pm(hasID(a.UpdateItem), "items:manage"))
{new_route}
"""


def sample_client() -> str:
    return """\
class ListmonkClient:
    async def _request(self, method, endpoint):
        return {}

    async def health_check(self):
        return await self._request("GET", "/api/health")

    async def update_item(self, item_id):
        return await self._request("PUT", f"/api/items/{item_id}")
"""


def contract(router: str) -> dict[str, object]:
    return build_contract(
        upstream_repository="knadh/listmonk",
        release="v6.2.0",
        commit="a" * 40,
        release_url="https://github.com/knadh/listmonk/releases/tag/v6.2.0",
        router_source=router,
        openapi_source=sample_openapi(),
    )


def test_extracts_routes_handlers_and_permissions() -> None:
    routes = extract_upstream_routes(sample_router())

    assert routes == [
        {
            "method": "GET",
            "path": "/api/health",
            "handlers": ["HealthCheck"],
            "permissions": [],
        },
        {
            "method": "PUT",
            "path": "/api/items/:id",
            "handlers": ["UpdateItem"],
            "permissions": ["items:manage"],
        },
    ]


def test_client_fstrings_match_upstream_path_parameters() -> None:
    calls = extract_client_calls(sample_client())

    assert [(call.method, call.path, call.client_method) for call in calls] == [
        ("GET", "/api/health", "health_check"),
        ("PUT", "/api/items/{}", "update_item"),
    ]


def test_maps_direct_client_usage_to_mcp_tools_and_resources() -> None:
    surfaces = extract_mcp_surfaces(
        """
@listmonk_tool(annotations=READ_ONLY)
async def check_listmonk_health():
    return await get_client().health_check()

@listmonk_resource("listmonk://items/{item_id}")
async def get_item(item_id):
    return await get_client().update_item(item_id)
""",
        {"health_check", "update_item"},
    )

    assert surfaces == {
        "health_check": ["tool:check_listmonk_health"],
        "update_item": ["resource:listmonk://items/{item_id}"],
    }


def test_new_upstream_route_requires_an_explicit_decision() -> None:
    calls = extract_client_calls(sample_client())
    original = contract(sample_router())
    original_policy = update_policy(original, calls, None, bootstrap=True)
    changed = contract(sample_router(include_new=True))

    policy = update_policy(changed, calls, original_policy)
    decisions = {
        (item["method"], item["path"]): item for item in policy["decisions"]
    }

    assert decisions[("POST", "/api/items")]["status"] == "review_required"
    assert decisions[("GET", "/api/health")]["status"] == "implemented"


def test_contract_id_tracks_api_content_instead_of_release_number() -> None:
    handlers = {
        "cmd/items.go": """
func (a *App) HealthCheck(c echo.Context) error { return nil }
func (a *App) UpdateItem(c echo.Context) error { return nil }
"""
    }
    first = build_contract(
        upstream_repository="knadh/listmonk",
        release="v6.2.0",
        commit="a" * 40,
        release_url="https://example.invalid/v6.2.0",
        router_source=sample_router(),
        openapi_source=sample_openapi(),
        handler_sources=handlers,
    )
    same_api_new_release = build_contract(
        upstream_repository="knadh/listmonk",
        release="v6.3.0",
        commit="b" * 40,
        release_url="https://example.invalid/v6.3.0",
        router_source=sample_router(),
        openapi_source=sample_openapi(),
        handler_sources=handlers,
    )
    changed_handler_source = build_contract(
        upstream_repository="knadh/listmonk",
        release="v6.3.0",
        commit="c" * 40,
        release_url="https://example.invalid/v6.3.0",
        router_source=sample_router(),
        openapi_source=sample_openapi(),
        handler_sources={
            "cmd/items.go": handlers["cmd/items.go"] + "\n// behavior changed\n"
        },
    )

    assert first["contractId"] == same_api_new_release["contractId"]
    assert first["contractId"] != changed_handler_source["contractId"]

    calls = extract_client_calls(sample_client())
    reviewed = update_policy(first, calls, None, bootstrap=True)
    pending_acknowledgement = update_policy(changed_handler_source, calls, reviewed)
    assert (
        pending_acknowledgement["contractId"]
        == changed_handler_source["contractId"]
    )
    assert pending_acknowledgement["reviewedContractId"] == first["contractId"]


def test_generated_repository_contract_is_current() -> None:
    errors, counts = validation_errors(ROOT)

    assert errors == []
    assert counts["reviewRequiredRoutes"] == 0
    assert counts["clientCalls"] >= counts["implementedRoutes"]


def test_every_recorded_bridge_release_has_an_explicit_status() -> None:
    matrix = json.loads((ROOT / "compatibility/bridge-releases.json").read_text())
    entries = {item["bridgeRelease"]: item for item in matrix["releases"]}

    assert entries["v0.4.33"]["verification"] == "source-verified"
    assert entries["v0.4.33"]["apiContractId"].startswith("lm-api:sha256:")
    assert all(item["verification"] for item in entries.values())
    assert set(discover_bridge_releases(ROOT)) <= set(entries)


def test_release_stamp_binds_an_exact_contract() -> None:
    current_contract = json.loads(
        (ROOT / "compatibility/listmonk-api-contract.json").read_text()
    )
    matrix = backfill_unknown_releases(None, ["v0.4.34"])

    stamped = stamp_bridge_release(
        matrix, current_contract, "0.4.34", "source-verified"
    )

    assert stamped["releases"] == [
        {
            "bridgeRelease": "v0.4.34",
            "apiContractId": current_contract["contractId"],
            "sourceRelease": "v6.2.0",
            "sourceCommit": "ef0a75872463f10a4848af6c547d1c057405453a",
            "upstreamDeclaredApiVersion": "1.0.0",
            "verification": "source-verified",
        }
    ]


def test_runtime_release_compatibility_uses_contract_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = {
        "contractId": "lm-api:sha256:expected",
        "compatibleListmonkReleases": ["v6.2.0"],
        "knownReleaseContracts": {
            "v6.2.0": "lm-api:sha256:expected",
            "v7.0.0": "lm-api:sha256:different",
        },
    }
    monkeypatch.setattr(
        api_compatibility, "get_api_contract_metadata", lambda: metadata
    )

    compatible = api_compatibility.evaluate_listmonk_release("v6.2.0")
    incompatible = api_compatibility.evaluate_listmonk_release("listmonk 7.0.0")
    unknown = api_compatibility.evaluate_listmonk_release("nightly")

    assert compatible["status"] == "compatible"
    assert incompatible["status"] == "incompatible"
    assert unknown["status"] == "unknown"
