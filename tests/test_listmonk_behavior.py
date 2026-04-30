import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkClient, normalize_body
from listmonk_mcp.config import Config
from listmonk_mcp.models import (
    CampaignTypeEnum,
    ContentTypeEnum,
    CreateCampaignModel,
    CreateTemplateModel,
)


class RecordingClient(ListmonkClient):
    def __init__(self) -> None:
        super().__init__(
            Config(
                url="http://localhost:9000",
                username="api-user",
                password="api-token",
            )
        )
        self.requests: list[dict[str, Any]] = []

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "json_data": json_data,
                "retry_count": retry_count,
            }
        )
        return {"data": {"id": 123, **(json_data or {})}}

    async def _request_form(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": None,
                "json_data": data,
                "retry_count": 0,
            }
        )
        return {"text": "<p>Preview</p>"}


class CampaignRecordingClient(RecordingClient):
    async def get_campaign(
        self, campaign_id: int, no_body: bool | None = None
    ) -> dict[str, Any]:
        del no_body
        return {
            "data": {
                "id": campaign_id,
                "name": "Draft",
                "subject": "Hello",
                "lists": [{"id": 1, "name": "Test"}],
                "type": "regular",
                "from_email": "Sender <sender@example.com>",
                "body": "<p>Hello</p>",
                "content_type": "html",
                "template": {"id": 3},
                "tags": ["test"],
                "messenger": "email",
            }
        }


def last_payload(client: RecordingClient) -> dict[str, Any]:
    payload = client.requests[-1]["json_data"]
    assert isinstance(payload, dict)
    return payload


def last_request(client: RecordingClient) -> dict[str, Any]:
    return client.requests[-1]


@pytest.mark.asyncio
async def test_update_subscriber_partial_name_omits_email() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, name="New Name")

    assert last_request(client)["method"] == "PATCH"
    assert last_request(client)["endpoint"] == "/api/subscribers/7"
    assert last_payload(client) == {"name": "New Name"}


@pytest.mark.asyncio
async def test_update_subscriber_partial_status_only() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, status="disabled")

    assert last_request(client)["method"] == "PATCH"
    assert last_payload(client) == {"status": "disabled"}


@pytest.mark.asyncio
async def test_update_subscriber_partial_lists() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, lists=[1, 2])

    assert last_request(client)["method"] == "PATCH"
    assert last_payload(client) == {"lists": [1, 2]}


@pytest.mark.asyncio
async def test_update_subscriber_full_update_still_sends_fields() -> None:
    client = RecordingClient()

    await client.update_subscriber(
        subscriber_id=7,
        email="ada@example.com",
        name="Ada",
        status="enabled",
        lists=[1],
        attribs={"role": "admin"},
    )

    assert last_payload(client) == {
        "email": "ada@example.com",
        "name": "Ada",
        "status": "enabled",
        "lists": [1],
        "attribs": {"role": "admin"},
    }


@pytest.mark.asyncio
async def test_update_subscriber_omits_none_fields() -> None:
    client = RecordingClient()

    await client.update_subscriber(
        subscriber_id=7,
        email=None,
        name="Ada",
        status=None,
        lists=None,
        attribs=None,
    )

    assert last_payload(client) == {"name": "Ada"}


@pytest.mark.asyncio
async def test_create_template_payload_includes_subject_for_tx() -> None:
    client = RecordingClient()

    await client.create_template(
        name="Transactional",
        subject="Receipt",
        body="<p>Hello</p>",
        type="tx",
    )

    assert last_payload(client) == {
        "name": "Transactional",
        "subject": "Receipt",
        "body": "<p>Hello</p>",
        "type": "tx",
        "is_default": False,
    }


@pytest.mark.asyncio
async def test_create_template_supports_campaign_visual_body_source() -> None:
    client = RecordingClient()

    await client.create_template(
        name="Visual",
        subject="Subject",
        body="<p>Hello</p>",
        type="campaign_visual",
        body_source='{"rows":[]}',
    )

    payload = last_payload(client)
    assert payload["type"] == "campaign_visual"
    assert payload["body_source"] == '{"rows":[]}'


def test_create_template_schema_requires_subject() -> None:
    schema = CreateTemplateModel.model_json_schema()

    assert "subject" in schema["required"]
    assert "subject" in inspect.signature(server.create_template).parameters


def test_create_template_model_requires_subject() -> None:
    with pytest.raises(ValidationError):
        CreateTemplateModel.model_validate(
            {"name": "Missing subject", "body": "<p>Hello</p>"}
        )


def test_normalize_body_converts_plain_text_to_html() -> None:
    body, content_type = normalize_body("Hello\n\nLine 2\nLine 3", "plain")

    assert body == "<p>Hello</p><p>Line 2<br>Line 3</p>"
    assert content_type == "html"


def test_normalize_body_escapes_plain_text_html() -> None:
    body, content_type = normalize_body("<script>x</script>\n<b>bold</b>", "plain")

    assert body == "<p>&lt;script&gt;x&lt;/script&gt;<br>&lt;b&gt;bold&lt;/b&gt;</p>"
    assert content_type == "html"


def test_normalize_body_leaves_html_unchanged() -> None:
    original = "<p>Hello<br>World</p>"

    assert normalize_body(original, "html") == (original, "html")


def test_normalize_body_leaves_plain_unchanged_when_disabled() -> None:
    original = "Hello\n\nLine 2\nLine 3"

    assert normalize_body(original, "plain", auto_convert_plain_to_html=False) == (
        original,
        "plain",
    )


@pytest.mark.asyncio
async def test_create_campaign_plain_without_conversion_sends_plain() -> None:
    client = RecordingClient()

    await client.create_campaign(
        name="Plain",
        subject="Subject",
        lists=[1],
        content_type="plain",
        body="Hello\n\nLine 2",
        auto_convert_plain_to_html=False,
    )

    payload = last_payload(client)
    assert payload["body"] == "Hello\n\nLine 2"
    assert payload["content_type"] == "plain"


@pytest.mark.asyncio
async def test_create_campaign_plain_with_conversion_sends_html() -> None:
    client = RecordingClient()

    await client.create_campaign(
        name="Plain",
        subject="Subject",
        lists=[1],
        content_type="plain",
        body="Hello\n\nLine 2",
    )

    payload = last_payload(client)
    assert payload["body"] == "<p>Hello</p><p>Line 2</p>"
    assert payload["content_type"] == "html"


@pytest.mark.asyncio
async def test_create_campaign_html_ignores_conversion_flag() -> None:
    client = RecordingClient()

    await client.create_campaign(
        name="HTML",
        subject="Subject",
        lists=[1],
        content_type="html",
        body="<p>Hello</p>",
        auto_convert_plain_to_html=True,
    )

    payload = last_payload(client)
    assert payload["body"] == "<p>Hello</p>"
    assert payload["content_type"] == "html"


@pytest.mark.asyncio
async def test_create_campaign_sends_swagger_fields() -> None:
    client = RecordingClient()

    await client.create_campaign(
        name="Campaign",
        subject="Subject",
        lists=[1],
        content_type="html",
        body="<p>Hello</p>",
        altbody="Hello",
        from_email="Sender <sender@example.com>",
        messenger="email",
        template_id=2,
        send_later=True,
        send_at="2026-05-01T10:00:00Z",
        headers=[{"X-Test": "1"}],
    )

    payload = last_payload(client)
    assert payload["altbody"] == "Hello"
    assert payload["from_email"] == "Sender <sender@example.com>"
    assert payload["messenger"] == "email"
    assert payload["template_id"] == 2
    assert payload["send_later"] is True
    assert payload["send_at"] == "2026-05-01T10:00:00Z"
    assert payload["headers"] == [{"X-Test": "1"}]


@pytest.mark.asyncio
async def test_added_swagger_endpoint_methods_use_expected_paths() -> None:
    client = RecordingClient()

    await client.get_public_lists()
    assert last_request(client)["method"] == "GET"
    assert last_request(client)["endpoint"] == "/api/public/lists"

    await client.get_media_file(7)
    assert last_request(client)["method"] == "GET"
    assert last_request(client)["endpoint"] == "/api/media/7"

    await client.delete_campaign(3)
    assert last_request(client)["method"] == "DELETE"
    assert last_request(client)["endpoint"] == "/api/campaigns/3"

    await client.set_default_template(4)
    assert last_request(client)["method"] == "PUT"
    assert last_request(client)["endpoint"] == "/api/templates/4/default"


@pytest.mark.asyncio
async def test_transactional_email_supports_multiple_recipient_modes() -> None:
    client = RecordingClient()

    await client.send_transactional_email(
        template_id=2,
        subscriber_emails=["external@example.com"],
        subscriber_mode="external",
        subject="Override",
        from_email="Sender <sender@example.com>",
        data={"order_id": "123"},
        headers=[{"X-Test": "1"}],
        messenger="email",
        altbody="Plain text",
    )

    assert last_payload(client) == {
        "template_id": 2,
        "data": {"order_id": "123"},
        "content_type": "html",
        "subscriber_emails": ["external@example.com"],
        "subscriber_mode": "external",
        "from_email": "Sender <sender@example.com>",
        "subject": "Override",
        "headers": [{"X-Test": "1"}],
        "messenger": "email",
        "altbody": "Plain text",
    }


@pytest.mark.asyncio
async def test_test_campaign_sends_campaign_payload_with_email_recipients() -> None:
    client = CampaignRecordingClient()

    await client.test_campaign(
        campaign_id=33,
        subscribers=["hello@ediblelandscapecreators.org"],
    )

    assert last_request(client)["method"] == "POST"
    assert last_request(client)["endpoint"] == "/api/campaigns/33/test"
    assert last_payload(client) == {
        "name": "Draft",
        "subject": "Hello",
        "lists": [1],
        "type": "regular",
        "from_email": "Sender <sender@example.com>",
        "body": "<p>Hello</p>",
        "content_type": "html",
        "template_id": 3,
        "tags": ["test"],
        "messenger": "email",
        "subscribers": ["hello@ediblelandscapecreators.org"],
    }


@pytest.mark.asyncio
async def test_subscriber_auxiliary_methods_use_swagger_paths() -> None:
    client = RecordingClient()

    await client.send_subscriber_optin(9)
    assert last_request(client)["method"] == "POST"
    assert last_request(client)["endpoint"] == "/api/subscribers/9/optin"

    await client.blocklist_subscriber(9)
    assert last_request(client)["method"] == "PUT"
    assert last_request(client)["endpoint"] == "/api/subscribers/9/blocklist"

    await client.manage_subscriber_lists(
        action="add",
        target_list_ids=[1],
        ids=[9],
        status="confirmed",
    )
    assert last_request(client)["method"] == "PUT"
    assert last_request(client)["endpoint"] == "/api/subscribers/lists"
    assert last_payload(client) == {
        "action": "add",
        "target_list_ids": [1],
        "ids": [9],
        "status": "confirmed",
    }


@pytest.mark.asyncio
async def test_get_subscriber_by_email_escapes_query_literal() -> None:
    client = RecordingClient()

    await client.get_subscriber_by_email("o'hara@example.com")

    assert last_request(client)["endpoint"] == "/api/subscribers"
    assert last_request(client)["params"]["query"] == (
        "subscribers.email = 'o''hara@example.com'"
    )


@pytest.mark.asyncio
async def test_misc_settings_admin_and_logs_methods_use_swagger_paths() -> None:
    client = RecordingClient()

    await client.get_server_config()
    assert last_request(client)["endpoint"] == "/api/config"

    await client.get_i18n_language("en")
    assert last_request(client)["endpoint"] == "/api/lang/en"

    await client.get_dashboard_charts()
    assert last_request(client)["endpoint"] == "/api/dashboard/charts"

    await client.get_dashboard_counts()
    assert last_request(client)["endpoint"] == "/api/dashboard/counts"

    await client.get_settings()
    assert last_request(client)["endpoint"] == "/api/settings"

    await client.update_settings({"app": {"site_name": "Listmonk"}})
    assert last_request(client)["method"] == "PUT"
    assert last_request(client)["endpoint"] == "/api/settings"

    await client.test_smtp_settings({"host": "smtp.example.com"})
    assert last_request(client)["method"] == "POST"
    assert last_request(client)["endpoint"] == "/api/settings/smtp/test"

    await client.reload_app()
    assert last_request(client)["endpoint"] == "/api/admin/reload"

    await client.get_logs()
    assert last_request(client)["endpoint"] == "/api/logs"


@pytest.mark.asyncio
async def test_bulk_subscriber_and_bounce_methods_use_swagger_paths() -> None:
    client = RecordingClient()

    await client.delete_subscribers([1, 2])
    assert last_request(client)["method"] == "DELETE"
    assert last_request(client)["endpoint"] == "/api/subscribers"
    assert last_request(client)["params"] == {"id": [1, 2]}

    await client.blocklist_subscribers(ids=[1, 2])
    assert last_request(client)["method"] == "PUT"
    assert last_request(client)["endpoint"] == "/api/subscribers/blocklist"

    await client.delete_subscribers_by_query("subscribers.email LIKE '%@example.com'")
    assert last_request(client)["endpoint"] == "/api/subscribers/query/delete"

    await client.blocklist_subscribers_by_query("subscribers.status = 'disabled'")
    assert last_request(client)["endpoint"] == "/api/subscribers/query/blocklist"

    await client.manage_subscriber_lists_by_query(
        query="subscribers.status = 'enabled'",
        action="add",
        target_list_ids=[1],
    )
    assert last_request(client)["endpoint"] == "/api/subscribers/query/lists"

    await client.delete_bounces(bounce_ids=[5, 6])
    assert last_request(client)["method"] == "DELETE"
    assert last_request(client)["endpoint"] == "/api/bounces"
    assert last_request(client)["params"] == {"all": False, "id": [5, 6]}


@pytest.mark.asyncio
async def test_campaign_preview_bulk_public_and_maintenance_paths() -> None:
    client = RecordingClient()

    await client.delete_campaigns(ids=[1, 2])
    assert last_request(client)["method"] == "DELETE"
    assert last_request(client)["endpoint"] == "/api/campaigns"

    await client.preview_campaign_body(3, "<p>Hello</p>", "html", template_id=4)
    assert last_request(client)["method"] == "POST"
    assert last_request(client)["endpoint"] == "/api/campaigns/3/preview"
    assert last_payload(client) == {
        "body": "<p>Hello</p>",
        "content_type": "html",
        "template_id": 4,
    }

    await client.preview_campaign_text(3, "Hello", "plain")
    assert last_request(client)["endpoint"] == "/api/campaigns/3/text"

    await client.create_public_subscription(
        name="Ada",
        email="ada@example.com",
        list_uuids=["list-uuid"],
    )
    assert last_request(client)["endpoint"] == "/api/public/subscription"
    assert last_payload(client) == {
        "name": "Ada",
        "email": "ada@example.com",
        "list_uuids": ["list-uuid"],
    }

    await client.delete_gc_subscribers("blocklisted")
    assert (
        last_request(client)["endpoint"] == "/api/maintenance/subscribers/blocklisted"
    )

    await client.delete_campaign_analytics("views", "2026-01-01")
    assert last_request(client)["endpoint"] == "/api/maintenance/analytics/views"
    assert last_payload(client) == {"before_date": "2026-01-01"}

    await client.delete_unconfirmed_subscriptions("2026-01-01")
    assert (
        last_request(client)["endpoint"] == "/api/maintenance/subscriptions/unconfirmed"
    )
    assert last_payload(client) == {"before_date": "2026-01-01"}


@pytest.mark.asyncio
async def test_create_campaign_tool_passes_conversion_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCampaignClient:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] | None = None

        async def create_campaign(self, **kwargs: Any) -> dict[str, Any]:
            self.kwargs = kwargs
            return {"data": {"id": 456}}

    fake_client = FakeCampaignClient()
    monkeypatch.setattr(server, "get_client", lambda: fake_client)

    await server.create_campaign(
        name="Plain",
        subject="Subject",
        lists=[1],
        content_type="plain",
        body="Hello",
        auto_convert_plain_to_html=False,
    )

    assert fake_client.kwargs is not None
    assert fake_client.kwargs["auto_convert_plain_to_html"] is False


def test_create_campaign_model_exposes_conversion_default() -> None:
    model = CreateCampaignModel(
        name="Campaign",
        subject="Subject",
        lists=[1],
        type=CampaignTypeEnum.regular,
        from_email=None,
        body="Hello",
        content_type=ContentTypeEnum.plain,
        altbody=None,
        template_id=None,
        tags=[],
        send_later=None,
        send_at=None,
        messenger=None,
        headers=None,
    )

    assert model.auto_convert_plain_to_html is True
