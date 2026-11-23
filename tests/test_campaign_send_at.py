from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkClient
from listmonk_mcp.config import Config

FUTURE = "2099-06-01T10:00:00+03:00"
FUTURE_UTC = "2099-06-01T07:00:00Z"
CAMPAIGN = {"id": 10, "status": "draft", "send_at": None, "lists": [{"id": 1}]}


@pytest.fixture
def listmonk(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[httpx.Response]], list[httpx.Request]]:
    def setup(responses: list[httpx.Response]) -> list[httpx.Request]:
        requests: list[httpx.Request] = []
        reply = iter(responses)

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.url.path == "/api/campaigns/10"
            return next(reply)

        config = Config(url="http://localhost:9000", username="u", password="p")
        upstream = ListmonkClient(config)
        upstream._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        monkeypatch.setattr(server, "_client", upstream)
        return requests

    return setup


def campaign_response(**fields: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": {**CAMPAIGN, **fields}})


@pytest.mark.parametrize("send_at", [FUTURE, None])
async def test_default_preview_and_confirmed_draft_date_edit_over_mcp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    listmonk: Callable[[list[httpx.Response]], list[httpx.Request]],
    send_at: str | None,
) -> None:
    existing = campaign_response(send_at=None if send_at else FUTURE_UTC)
    requests = listmonk(
        [
            existing,
            existing,
            campaign_response(),
            campaign_response(send_at=FUTURE_UTC if send_at else None),
        ]
    )
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("LISTMONK_MCP_AUDIT_ENABLED", "true")
    monkeypatch.setenv("LISTMONK_MCP_AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv("LISTMONK_MCP_READ_ONLY", "true")
    args = {"campaignId": 10, "sendAt": send_at}

    async with Client(server.mcp) as client:
        preview = await client.call_tool("safe_set_campaign_send_at", args)
        assert preview.structured_content is not None
        assert preview.structured_content["success"] is True
        assert preview.structured_content["dryRun"] is True
        assert [request.method for request in requests] == ["GET"]

        apply_args = {**args, "dryRun": False, "confirmApply": True}
        blocked = await client.call_tool("safe_set_campaign_send_at", apply_args)
        assert blocked.structured_content is not None
        assert blocked.structured_content["error"]["type"] == "read_only"
        assert [request.method for request in requests] == ["GET"]

        monkeypatch.setenv("LISTMONK_MCP_READ_ONLY", "false")
        applied = await client.call_tool("safe_set_campaign_send_at", apply_args)
        assert applied.structured_content is not None
        assert applied.structured_content["success"] is True
        assert applied.structured_content["status"] == "draft"

    assert [request.method for request in requests] == ["GET", "GET", "PUT", "GET"]
    payload = json.loads(requests[2].content)
    assert payload["send_at"] == send_at
    assert payload["lists"] == [1]
    assert "status" not in payload
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert [event["riskClass"] for event in events] == ["MUTATING", "MUTATING"]
    assert [event["result"] for event in events] == ["blocked", "success"]


@pytest.mark.parametrize(
    ("send_at", "confirm", "message"),
    [
        (FUTURE, False, "confirmApply=true"),
        ("2099-06-01T10:00:00", True, "timezone offset"),
        ("2099-06-01T10:00:00+03:99", True, "timezone offset"),
        ("not-a-date", True, "ISO 8601"),
        ("2000-01-01T00:00:00Z", True, "in the future"),
    ],
)
async def test_invalid_draft_date_edit_is_blocked_before_request(
    monkeypatch: pytest.MonkeyPatch, send_at: str, confirm: bool, message: str
) -> None:
    def unexpected_client() -> ListmonkClient:
        pytest.fail("Invalid request should be blocked before accessing Listmonk")

    monkeypatch.setattr(server, "get_client", unexpected_client)
    result = await server.safe_set_campaign_send_at(10, send_at, False, confirm)
    assert result["success"] is False
    assert message in result["blockers"][0]


@pytest.mark.parametrize(
    ("responses", "methods", "message"),
    [
        ([campaign_response(status="scheduled")], ["GET"], "must be in draft status"),
        (
            [campaign_response(), campaign_response(), campaign_response(status="scheduled")],
            ["GET", "PUT", "GET"],
            "status was not draft",
        ),
        (
            [campaign_response(), campaign_response(), campaign_response()],
            ["GET", "PUT", "GET"],
            "stored a different sendAt value",
        ),
        (
            [campaign_response(), campaign_response(), httpx.Response(404)],
            ["GET", "PUT", "GET"],
            "Could not re-read",
        ),
    ],
)
async def test_draft_date_edit_fails_if_state_cannot_be_verified(
    listmonk: Callable[[list[httpx.Response]], list[httpx.Request]],
    responses: list[httpx.Response],
    methods: list[str],
    message: str,
) -> None:
    requests = listmonk(responses)
    result = await server.safe_set_campaign_send_at(10, FUTURE, False, True)
    assert result["success"] is False
    assert message in (result.get("error", {}).get("message") or result["blockers"][0])
    assert [request.method for request in requests] == methods
    await server.close_shared_client()
