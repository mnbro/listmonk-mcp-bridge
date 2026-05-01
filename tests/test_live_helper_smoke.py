from __future__ import annotations

import os
from pathlib import Path

import pytest

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkClient
from listmonk_mcp.config import Config

pytestmark = pytest.mark.skipif(
    os.getenv("LISTMONK_MCP_RUN_LIVE_TESTS") != "true",
    reason="live helper smoke tests require LISTMONK_MCP_RUN_LIVE_TESTS=true",
)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for live helper smoke tests")
    return value


def _live_config() -> Config:
    return Config(
        url=_required_env("LISTMONK_MCP_URL"),
        username=_required_env("LISTMONK_MCP_USERNAME"),
        password=_required_env("LISTMONK_MCP_PASSWORD"),
    )


@pytest.mark.asyncio
async def test_live_llm_helper_read_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    list_id = int(_required_env("LISTMONK_MCP_SMOKE_LIST_ID"))
    client = ListmonkClient(_live_config())
    monkeypatch.setattr(server, "get_client", lambda: client)
    monkeypatch.setattr(server, "_data_dir", tmp_path)
    monkeypatch.setattr(server, "_sync_log_path", tmp_path / "sync_logs.json")
    monkeypatch.setattr(
        server, "_send_audit_log_path", tmp_path / "send_audit_log.json"
    )
    monkeypatch.setattr(
        server, "_idempotency_keys_path", tmp_path / "idempotency_keys.json"
    )

    try:
        health = await server.check_listmonk_health()
        audience = await server.audience_summary(listIds=[list_id])
        fields = await server.personalization_fields_report(
            listIds=[list_id], sampleSize=25
        )
        validation = await server.validate_message_personalization(
            subject="Hello {{ .Subscriber.Name }}",
            body="This is a live helper smoke test.",
            listIds=[list_id],
        )

        assert health["success"] is True
        assert audience["success"] is True
        assert fields["success"] is True
        assert validation["success"] is True

        subscriber_id = os.getenv("LISTMONK_MCP_SMOKE_SUBSCRIBER_ID")
        subscriber_email = os.getenv("LISTMONK_MCP_SMOKE_EMAIL")
        if subscriber_id or subscriber_email:
            context = await server.get_subscriber_context(
                subscriberId=int(subscriber_id) if subscriber_id else None,
                email=subscriber_email,
            )
            assert "success" in context
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_live_safe_test_campaign_smoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign_id = int(_required_env("LISTMONK_MCP_SMOKE_CAMPAIGN_ID"))
    recipient = _required_env("LISTMONK_MCP_SMOKE_EMAIL")
    client = ListmonkClient(_live_config())
    monkeypatch.setattr(server, "get_client", lambda: client)
    monkeypatch.setattr(server, "_data_dir", tmp_path)
    monkeypatch.setattr(
        server, "_send_audit_log_path", tmp_path / "send_audit_log.json"
    )

    try:
        blocked = await server.safe_test_campaign(
            campaignId=campaign_id,
            testRecipients=[recipient],
            confirmSend=False,
        )
        assert blocked["success"] is False
        assert blocked["error"]["error_type"] == "SendConfirmationRequired"

        if os.getenv("LISTMONK_MCP_RUN_LIVE_SEND_TESTS") != "true":
            pytest.skip(
                "live test campaign send requires LISTMONK_MCP_RUN_LIVE_SEND_TESTS=true"
            )

        sent = await server.safe_test_campaign(
            campaignId=campaign_id,
            testRecipients=[recipient],
            confirmSend=True,
        )
        assert sent["success"] is True
        assert sent["sent"] is True
        assert sent["auditId"].startswith("audit-")
    finally:
        await client.close()
