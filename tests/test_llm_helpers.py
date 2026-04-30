from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkAPIError


class HelperClient:
    def __init__(self) -> None:
        self.subscribers: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "email": "jane@example.com",
                "name": "Jane",
                "status": "enabled",
                "attribs": {"birthday": "1990-05-10", "customer_type": "vip"},
                "tags": ["existing"],
                "lists": [{"id": 1}],
            },
            2: {
                "id": 2,
                "email": "disabled@example.com",
                "name": "",
                "status": "disabled",
                "attribs": {"customer_type": "standard"},
                "tags": ["customer"],
                "lists": [{"id": 1}],
            },
            3: {
                "id": 3,
                "email": "blocked@example.com",
                "name": "Blocked",
                "status": "blocklisted",
                "attribs": {},
                "tags": [],
                "lists": [{"id": 2}],
            },
        }
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.sent_campaigns: list[int] = []
        self.scheduled_campaigns: list[dict[str, Any]] = []
        self.test_sends: list[dict[str, Any]] = []
        self.tx_sends: list[dict[str, Any]] = []
        self.campaigns: dict[int, dict[str, Any]] = {
            10: {
                "id": 10,
                "name": "April Newsletter",
                "subject": "Hello {{ .Subscriber.Name }}",
                "body": "Update for {{customer_type}}",
                "status": "draft",
                "lists": [{"id": 1, "name": "Main"}],
                "content_type": "html",
            },
            11: {
                "id": 11,
                "name": "Broken",
                "subject": "",
                "body": "",
                "status": "sent",
                "lists": [],
            },
            12: {
                "id": 12,
                "name": "Aggregate Stats",
                "subject": "Stats",
                "body": "Stats",
                "status": "sent",
                "lists": [{"id": 1, "name": "Main"}],
                "views": 7,
                "clicks": 3,
                "bounces": 1,
                "sent": 4,
                "to_send": 0,
            },
            13: {
                "id": 13,
                "name": "No Detailed Analytics",
                "subject": "Stats",
                "body": "Stats",
                "status": "sent",
                "lists": [{"id": 1, "name": "Main"}],
                "views": 10,
                "clicks": 2,
            },
        }

    async def get_subscribers(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or "")
        if "jane@example.com" in query:
            return {"data": {"results": [self.subscribers[1]], "total": 1}}
        if "subscribers.email" in query:
            return {"data": {"results": [], "total": 0}}
        list_ids = set(kwargs.get("list_ids") or [])
        results = list(self.subscribers.values())
        if list_ids:
            results = [
                subscriber
                for subscriber in results
                if any(
                    item.get("id") in list_ids for item in subscriber.get("lists", [])
                )
            ]
        return {"data": {"results": results, "total": len(results)}}

    async def get_subscriber_by_email(self, email: str) -> dict[str, Any]:
        for subscriber in self.subscribers.values():
            if subscriber["email"] == email:
                return {"data": subscriber}
        return {"data": None}

    async def get_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        subscriber = self.subscribers.get(subscriber_id)
        return {"data": subscriber} if subscriber else {"data": None}

    async def create_subscriber(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        return {"data": {"id": 99, **kwargs}}

    async def update_subscriber(
        self, subscriber_id: int, **kwargs: Any
    ) -> dict[str, Any]:
        self.updated.append({"subscriber_id": subscriber_id, **kwargs})
        self.subscribers[subscriber_id] = {**self.subscribers[subscriber_id], **kwargs}
        return {"data": self.subscribers[subscriber_id]}

    async def get_subscriber_bounces(self, subscriber_id: int) -> dict[str, Any]:
        return {
            "data": {
                "results": [{"id": 1, "subscriber_id": subscriber_id}]
                if subscriber_id == 3
                else []
            }
        }

    async def get_list_subscribers(
        self, list_id: int, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        del page, per_page
        results = [
            subscriber
            for subscriber in self.subscribers.values()
            if any(item.get("id") == list_id for item in subscriber.get("lists", []))
        ]
        return {"data": {"results": results, "total": len(results)}}

    async def get_campaign(
        self, campaign_id: int, no_body: bool | None = None
    ) -> dict[str, Any]:
        del no_body
        return {"data": self.campaigns.get(campaign_id)}

    async def get_campaign_analytics(
        self,
        campaign_id: int,
        type: str = "views",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        if campaign_id in {12, 13}:
            raise ListmonkAPIError("not found", status_code=404)
        del campaign_id, from_date, to_date
        if type == "views":
            return {
                "data": [{"id": "v1", "subscriber_id": 1, "email": "jane@example.com"}]
            }
        if type == "clicks":
            return {
                "data": [{"id": "c1", "subscriber_id": 1, "url": "https://example.com"}]
            }
        return {"data": {"total": 0}}

    async def test_campaign(
        self, campaign_id: int, subscribers: list[str]
    ) -> dict[str, Any]:
        self.test_sends.append({"campaign_id": campaign_id, "subscribers": subscribers})
        return {"data": {"sent": True}}

    async def send_campaign(self, campaign_id: int) -> dict[str, Any]:
        self.sent_campaigns.append(campaign_id)
        return {"data": {"id": campaign_id, "status": "running"}}

    async def schedule_campaign(self, campaign_id: int, send_at: str) -> dict[str, Any]:
        self.scheduled_campaigns.append(
            {"campaign_id": campaign_id, "send_at": send_at}
        )
        return {"data": {"id": campaign_id, "send_at": send_at}}

    async def get_template(
        self, template_id: int, no_body: bool | None = None
    ) -> dict[str, Any]:
        del no_body
        return {"data": {"id": template_id, "name": "Template", "body": "<p>Hello</p>"}}

    async def send_transactional_email(self, **kwargs: Any) -> dict[str, Any]:
        self.tx_sends.append(kwargs)
        return {"data": {"id": "msg-123", **kwargs}}


@pytest.fixture()
def helper_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> HelperClient:
    client = HelperClient()
    monkeypatch.setattr(server, "get_client", lambda: client)
    monkeypatch.setattr(server, "_data_dir", tmp_path)
    monkeypatch.setattr(server, "_sync_log_path", tmp_path / "sync_logs.json")
    monkeypatch.setattr(
        server, "_send_audit_log_path", tmp_path / "send_audit_log.json"
    )
    monkeypatch.setattr(
        server, "_idempotency_keys_path", tmp_path / "idempotency_keys.json"
    )
    return client


@pytest.mark.asyncio
async def test_upsert_subscriber_profiles_dry_run_does_not_modify(
    helper_client: HelperClient,
) -> None:
    result = await server.upsert_subscriber_profiles(
        [{"email": "new@example.com", "name": "New", "listIds": [1]}],
        dryRun=True,
    )

    assert result["created"] == 0
    assert result["plannedCreated"] == 1
    assert helper_client.created == []


@pytest.mark.asyncio
async def test_upsert_subscriber_profiles_creates_and_updates_with_merge(
    helper_client: HelperClient,
) -> None:
    result = await server.upsert_subscriber_profiles(
        [
            {
                "email": "new@example.com",
                "name": "New",
                "attributes": {"city": "New York"},
                "tags": ["fresh"],
                "listIds": [1],
            },
            {
                "email": "jane@example.com",
                "attributes": {"city": "London"},
                "tags": ["vip"],
                "listIds": [2],
            },
        ],
        dryRun=False,
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert helper_client.created[0]["attribs"]["city"] == "New York"
    update = helper_client.updated[0]
    assert update["attribs"]["birthday"] == "1990-05-10"
    assert update["attribs"]["city"] == "London"
    assert set(update["attribs"]["tags"]) == {"existing", "vip"}
    assert update["lists"] == [1, 2]


@pytest.mark.asyncio
async def test_get_subscriber_context_by_email_and_missing(
    helper_client: HelperClient,
) -> None:
    found = await server.get_subscriber_context(email="jane@example.com")
    missing = await server.get_subscriber_context(email="missing@example.com")

    assert found["success"] is True
    assert found["subscriber"]["id"] == 1
    assert found["engagementSummary"]["bounces"] == 0
    assert missing["success"] is False
    assert missing["error"]["error_type"] == "NotFound"


@pytest.mark.asyncio
async def test_get_subscriber_context_by_id(helper_client: HelperClient) -> None:
    result = await server.get_subscriber_context(subscriberId=3)

    assert result["success"] is True
    assert result["bounceStatus"]["count"] == 1


@pytest.mark.asyncio
async def test_audience_summary_counts_coverage_and_warnings(
    helper_client: HelperClient,
) -> None:
    result = await server.audience_summary(listIds=[1, 2])

    assert result["estimatedCount"] == 3
    assert result["activeCount"] == 1
    assert result["disabledCount"] == 1
    assert result["blocklistedCount"] == 1
    assert result["attributeCoverage"]["customer_type"] > 0
    assert result["warnings"]


@pytest.mark.asyncio
async def test_personalization_fields_report_marks_safe_and_risky(
    helper_client: HelperClient,
) -> None:
    result = await server.personalization_fields_report(listIds=[1], sampleSize=10)

    assert "customer_type" in result["recommendedSafeFields"]
    assert "name" in result["availableFields"]
    assert "birthday" in result["riskyFields"]


@pytest.mark.asyncio
async def test_validate_message_personalization_detects_missing_and_low_coverage(
    helper_client: HelperClient,
) -> None:
    result = await server.validate_message_personalization(
        subject="Hello {{name}}",
        body="You have {{birthday}} and {{missing_field}}",
        listIds=[1],
    )

    assert "missing_field" in result["missingVariables"]
    assert "birthday" in result["lowCoverageVariables"]
    assert result["riskLevel"] == "high"


@pytest.mark.asyncio
async def test_validate_message_personalization_detects_listmonk_go_templates(
    helper_client: HelperClient,
) -> None:
    result = await server.validate_message_personalization(
        subject="Hello {{ .Subscriber.Name }}",
        body=(
            "Your birthday is {{ .Subscriber.Attribs.birthday }}. "
            "Campaign {{ .Campaign.Name }} / {{ .Campaign.Subject }}"
        ),
        listIds=[2],
    )

    assert result["usedVariables"] == ["birthday", "name"]
    assert result["missingVariables"] == ["birthday"]
    assert ".Campaign.Name" not in result["missingVariables"]
    assert result["coverageByVariable"]["name"] == 1
    assert result["coverageByVariable"]["birthday"] == 0
    assert result["riskLevel"] == "high"


@pytest.mark.asyncio
async def test_campaign_risk_check_low_and_high(helper_client: HelperClient) -> None:
    low = await server.campaign_risk_check(campaignId=10)
    high = await server.campaign_risk_check(campaignId=11)

    assert low["riskLevel"] in {"low", "medium"}
    assert low["audience"]["listIds"] == [1]
    assert low["audience"]["estimatedCount"] == 2
    assert "Campaign has no target lists in the returned payload" not in low["blockers"]
    assert high["riskLevel"] == "high"
    assert high["blockers"]


@pytest.mark.asyncio
async def test_safe_send_campaign_blocks_and_sends(helper_client: HelperClient) -> None:
    without_confirm = await server.safe_send_campaign(campaignId=10)
    unapproved = await server.safe_send_campaign(
        campaignId=10,
        confirmSend=True,
        approval={"required": True, "status": "pending"},
        requireTestSend=False,
    )
    sent = await server.safe_send_campaign(
        campaignId=10,
        confirmSend=True,
        approval={"required": True, "status": "approved", "approvalId": "approval-1"},
        requireTestSend=True,
        testRecipients=["test@example.com"],
    )

    assert without_confirm["success"] is False
    assert unapproved["success"] is False
    assert sent["sent"] is True
    assert helper_client.test_sends
    assert helper_client.sent_campaigns == [10]
    assert sent["auditId"].startswith("audit-")


@pytest.mark.asyncio
async def test_safe_test_campaign_blocks_and_sends(helper_client: HelperClient) -> None:
    blocked = await server.safe_test_campaign(
        campaignId=10,
        testRecipients=["test@example.com"],
    )
    sent = await server.safe_test_campaign(
        campaignId=10,
        testRecipients=["test@example.com"],
        confirmSend=True,
    )
    invalid = await server.safe_test_campaign(
        campaignId=10,
        testRecipients=["not-an-email"],
        confirmSend=True,
    )

    assert blocked["success"] is False
    assert blocked["error"]["error_type"] == "SendConfirmationRequired"
    assert invalid["success"] is False
    assert invalid["blockers"] == ["Invalid email recipient: not-an-email"]
    assert sent["sent"] is True
    assert helper_client.test_sends[-1] == {
        "campaign_id": 10,
        "subscribers": ["test@example.com"],
    }
    assert sent["auditId"].startswith("audit-")


@pytest.mark.asyncio
async def test_safe_schedule_campaign_blocks_and_schedules(
    helper_client: HelperClient,
) -> None:
    blocked = await server.safe_schedule_campaign(
        campaignId=10, sendAt="2026-05-01T09:00:00Z"
    )
    scheduled = await server.safe_schedule_campaign(
        campaignId=10,
        sendAt="2026-05-01T09:00:00Z",
        confirmSchedule=True,
        approval={"required": True, "status": "approved"},
    )

    assert blocked["success"] is False
    assert scheduled["scheduled"] is True
    assert helper_client.scheduled_campaigns == [
        {"campaign_id": 10, "send_at": "2026-05-01T09:00:00Z"}
    ]
    assert scheduled["auditId"].startswith("audit-")


@pytest.mark.asyncio
async def test_safe_send_transactional_email_idempotency(
    helper_client: HelperClient,
) -> None:
    blocked = await server.safe_send_transactional_email(
        templateId=1,
        recipientEmail="jane@example.com",
        data={"name": "Jane", "nested": {"value": 1}},
    )
    first = await server.safe_send_transactional_email(
        templateId=1,
        recipientEmail="jane@example.com",
        data={"name": "Jane", "nested": {"value": 1}},
        confirmSend=True,
        idempotencyKey="event-1",
    )
    second = await server.safe_send_transactional_email(
        templateId=1,
        recipientEmail="jane@example.com",
        confirmSend=True,
        idempotencyKey="event-1",
    )

    assert blocked["success"] is False
    assert first["sent"] is True
    assert second["skipped"] is True
    assert len(helper_client.tx_sends) == 1
    assert helper_client.tx_sends[0]["data"] == {"name": "Jane", "nested": {"value": 1}}


@pytest.mark.asyncio
async def test_campaign_performance_summary_and_events(
    helper_client: HelperClient,
) -> None:
    summary = await server.campaign_performance_summary(campaignId=10)
    events = await server.export_engagement_events(
        campaignId=10, eventTypes=["email_viewed", "email_bounced"]
    )

    assert summary["views"] == 1
    assert summary["clicks"] == 1
    assert events["events"][0]["eventType"] == "email_viewed"
    assert events["supported"] is False
    assert events["unsupported"][0]["eventType"] == "email_bounced"


@pytest.mark.asyncio
async def test_campaign_performance_summary_uses_campaign_field_fallback(
    helper_client: HelperClient,
) -> None:
    summary = await server.campaign_performance_summary(campaignId=12)

    assert summary["views"] == 7
    assert summary["clicks"] == 3
    assert summary["bounces"] == 1
    assert summary["sent"] == 4
    assert summary["toSend"] == 0
    assert summary["analyticsSource"] == "campaign_fields"
    assert summary["warnings"] == [
        "Detailed analytics endpoint unavailable; using aggregate campaign fields."
    ]


@pytest.mark.asyncio
async def test_export_engagement_events_handles_missing_detailed_analytics(
    helper_client: HelperClient,
) -> None:
    result = await server.export_engagement_events(
        campaignId=13, eventTypes=["email_viewed", "email_clicked"]
    )

    assert result == {
        "success": True,
        "supported": False,
        "events": [],
        "unsupported": [
            {
                "eventType": "email_viewed",
                "reason": "Detailed analytics endpoint unavailable; event-level data is not available for this campaign.",
            },
            {
                "eventType": "email_clicked",
                "reason": "Detailed analytics endpoint unavailable; event-level data is not available for this campaign.",
            },
        ],
        "warnings": [
            "Listmonk returned 404 for detailed analytics; use campaign_performance_summary for aggregate metrics."
        ],
    }


@pytest.mark.asyncio
async def test_campaign_markdown_and_postmortem_exports(
    helper_client: HelperClient,
) -> None:
    no_body = await server.export_campaign_markdown(
        campaignId=10, includeBody=False, includeStats=False
    )
    with_body = await server.export_campaign_markdown(
        campaignId=10, includeBody=True, includeStats=True
    )
    postmortem = await server.export_campaign_postmortem_markdown(campaignId=10)

    assert "## Body" not in no_body["markdown"]
    assert "## Stats" not in no_body["markdown"]
    assert "## Body" in with_body["markdown"]
    assert "## Stats" in with_body["markdown"]
    assert postmortem["title"].startswith("Postmortem")


@pytest.mark.asyncio
async def test_export_subscriber_communication_summary(
    helper_client: HelperClient,
) -> None:
    result = await server.export_subscriber_communication_summary(
        email="jane@example.com"
    )

    assert result["success"] is True
    assert "Communication Summary" in result["markdown"]
    assert "engagement" in result
    assert result["subscriber"]["email"] == "jane@example.com"
