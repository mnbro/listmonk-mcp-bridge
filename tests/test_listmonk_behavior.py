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


def last_payload(client: RecordingClient) -> dict[str, Any]:
    payload = client.requests[-1]["json_data"]
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_update_subscriber_partial_name_omits_email() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, name="New Name")

    assert last_payload(client) == {"name": "New Name"}


@pytest.mark.asyncio
async def test_update_subscriber_partial_status_only() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, status="disabled")

    assert last_payload(client) == {"status": "disabled"}


@pytest.mark.asyncio
async def test_update_subscriber_partial_lists() -> None:
    client = RecordingClient()

    await client.update_subscriber(subscriber_id=7, lists=[1, 2])

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
        send_at=None,
        messenger=None,
    )

    assert model.auto_convert_plain_to_html is True
