from typing import Any

import pytest

from listmonk_mcp import server
from listmonk_mcp.client import ListmonkAPIError
from listmonk_mcp.exceptions import safe_execute_async


class FakeListmonkClient:
    async def get_list_subscribers(
        self,
        list_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> dict[str, Any]:
        return {
            "data": {
                "results": [
                    {
                        "id": 1,
                        "email": "ada@example.com",
                        "name": "Ada Lovelace",
                        "status": "enabled",
                    },
                    {
                        "id": 2,
                        "email": "grace@example.com",
                        "name": "Grace Hopper",
                        "status": "enabled",
                    },
                ],
                "total": 2,
            }
        }


class FakeSideEffectClient:
    async def delete_campaign(self, campaign_id: int) -> dict[str, Any]:
        return {"data": {"id": campaign_id}}

    async def send_campaign(self, campaign_id: int) -> dict[str, Any]:
        return {"data": {"id": campaign_id}}

    async def send_transactional_email(self, **kwargs: Any) -> dict[str, Any]:
        return {"data": kwargs}

    async def delete_subscribers_by_query(self, query: str) -> dict[str, Any]:
        return {"data": {"query": query}}


def test_create_production_server_returns_registered_server() -> None:
    assert server.create_production_server() is server.mcp


@pytest.mark.asyncio
async def test_reported_tool_schemas_include_documented_arguments() -> None:
    tools = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    assert set(tools["update_settings"]["properties"]) == {"settings", "confirm"}
    assert tools["update_settings"]["required"] == ["settings"]
    assert tools["update_settings"]["properties"]["settings"]["type"] == "object"
    assert "smtp" in tools["update_settings"]["properties"]["settings"]["properties"]

    assert set(tools["test_smtp_settings"]["properties"]) == {"settings"}
    assert tools["test_smtp_settings"]["required"] == ["settings"]
    assert tools["test_smtp_settings"]["properties"]["settings"]["type"] == "object"
    assert "host" in tools["test_smtp_settings"]["properties"]["settings"]["properties"]

    assert set(tools["import_subscribers"]["properties"]) == {"file_path", "params"}
    assert tools["import_subscribers"]["required"] == ["file_path", "params"]
    import_params = tools["import_subscribers"]["properties"]["params"]
    assert import_params["required"] == ["mode", "delim"]
    assert import_params["properties"]["mode"]["enum"] == ["subscribe", "blocklist"]

    assert set(tools["batch_replace_in_campaign_body"]["properties"]) == {
        "campaign_id",
        "replacements",
    }
    assert tools["batch_replace_in_campaign_body"]["required"] == [
        "campaign_id",
        "replacements",
    ]
    replacement_items = tools["batch_replace_in_campaign_body"]["properties"][
        "replacements"
    ]["items"]
    assert replacement_items["required"] == ["search", "replace"]
    assert set(replacement_items["properties"]) == {"search", "replace"}


@pytest.mark.asyncio
async def test_destructive_tools_are_annotated_and_require_confirmation() -> None:
    destructive_tools = {
        "delete_subscriber_bounces",
        "blocklist_subscriber",
        "blocklist_subscribers",
        "delete_subscribers_by_query",
        "blocklist_subscribers_by_query",
        "update_subscriber",
        "manage_subscriber_lists",
        "manage_subscriber_lists_by_query",
        "change_subscriber_status",
        "remove_subscriber",
        "remove_subscribers",
        "delete_bounce",
        "delete_bounces",
        "delete_mailing_list",
        "delete_mailing_lists",
        "delete_campaign",
        "delete_campaigns",
        "delete_template",
        "delete_media_file",
        "stop_import_subscribers",
        "delete_gc_subscribers",
        "delete_campaign_analytics",
        "delete_unconfirmed_subscriptions",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    for tool_name in destructive_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is True
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.idempotentHint is False
        assert tool.inputSchema["properties"]["confirm"]["type"] == "boolean"

    result = await server.delete_campaign(campaign_id=7)

    assert result["success"] is False
    assert result["error"]["error_type"] == "ConfirmationRequired"
    assert result["error"]["confirm_required"] is True
    assert result["error"]["context"] == {"campaign_id": 7}

    result = await server.change_subscriber_status(
        subscriber_id=11, status="blocklisted"
    )

    assert result["success"] is False
    assert result["error"]["error_type"] == "ConfirmationRequired"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        (server.update_settings, {"settings": {"app": {"site_name": "Staging"}}}),
        (server.reload_app, {}),
        (server.update_subscriber, {"subscriber_id": 1, "status": "blocklisted"}),
        (server.update_subscriber, {"subscriber_id": 1, "lists": [1]}),
        (
            server.manage_subscriber_lists,
            {"action": "remove", "target_list_ids": [1], "subscriber_ids": [1]},
        ),
        (
            server.manage_subscriber_lists_by_query,
            {
                "query": "subscribers.status = 'enabled'",
                "action": "unsubscribe",
                "target_list_ids": [1],
            },
        ),
        (server.delete_subscriber_bounces, {"subscriber_id": 1}),
        (server.blocklist_subscriber, {"subscriber_id": 1}),
        (server.blocklist_subscribers, {"subscriber_ids": [1]}),
        (
            server.delete_subscribers_by_query,
            {"query": "subscribers.email LIKE '%@example.com'"},
        ),
        (
            server.blocklist_subscribers_by_query,
            {"query": "subscribers.status = 'disabled'"},
        ),
        (server.remove_subscriber, {"subscriber_id": 1}),
        (server.remove_subscribers, {"subscriber_ids": [1]}),
        (server.delete_bounce, {"bounce_id": 1}),
        (server.delete_bounces, {"bounce_ids": [1]}),
        (server.delete_mailing_list, {"list_id": 1}),
        (server.delete_mailing_lists, {"list_ids": [1]}),
        (server.stop_import_subscribers, {}),
        (server.delete_campaign, {"campaign_id": 1}),
        (server.delete_campaigns, {"campaign_ids": [1]}),
        (server.delete_template, {"template_id": 1}),
        (server.delete_media_file, {"media_id": 1}),
        (server.delete_gc_subscribers, {"type": "blocklisted"}),
        (
            server.delete_campaign_analytics,
            {"type": "views", "before_date": "2026-01-01"},
        ),
        (server.delete_unconfirmed_subscriptions, {"before_date": "2026-01-01"}),
    ],
)
async def test_all_confirmation_guardrails_block_without_confirm(
    tool: Any, kwargs: dict[str, Any]
) -> None:
    result = await tool(**kwargs)

    assert result["success"] is False
    assert result["error"]["error_type"] == "ConfirmationRequired"
    assert result["error"]["confirm_required"] is True


@pytest.mark.asyncio
async def test_email_sending_tools_are_marked_side_effecting_and_require_confirmation() -> (
    None
):
    email_tools = {
        "send_subscriber_optin",
        "send_campaign",
        "test_campaign",
        "send_transactional_email",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    for tool_name in email_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is False
        assert tool.annotations.openWorldHint is True
        assert tool.inputSchema["properties"]["confirm_send"]["type"] == "boolean"

    result = await server.send_campaign(campaign_id=7)

    assert result["success"] is False
    assert result["error"]["error_type"] == "SendConfirmationRequired"
    assert result["error"]["confirm_required"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        (server.send_subscriber_optin, {"subscriber_id": 1}),
        (server.send_campaign, {"campaign_id": 1}),
        (server.test_campaign, {"campaign_id": 1, "subscribers": ["test@example.com"]}),
        (
            server.send_transactional_email,
            {"template_id": 1, "subscriber_email": "test@example.com"},
        ),
    ],
)
async def test_all_email_guardrails_block_without_confirm_send(
    tool: Any, kwargs: dict[str, Any]
) -> None:
    result = await tool(**kwargs)

    assert result["success"] is False
    assert result["error"]["error_type"] == "SendConfirmationRequired"
    assert result["error"]["confirm_required"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        (server.get_server_config, {}),
        (server.get_settings, {}),
        (server.get_logs, {}),
        (server.get_subscriber_export, {"subscriber_id": 1}),
    ],
)
async def test_sensitive_read_guardrails_block_without_confirm_read(
    tool: Any, kwargs: dict[str, Any]
) -> None:
    result = await tool(**kwargs)

    assert result["success"] is False
    assert result["error"]["error_type"] == "ReadConfirmationRequired"
    assert result["error"]["confirm_required"] is True


@pytest.mark.asyncio
async def test_confirmed_operations_emit_audit_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(server, "get_client", lambda: FakeSideEffectClient())

    with caplog.at_level("WARNING", logger="listmonk_mcp.audit"):
        delete_result = await server.delete_campaign(campaign_id=7, confirm=True)
        send_result = await server.send_campaign(campaign_id=8, confirm_send=True)

    assert delete_result["success"] is True
    assert send_result["success"] is True
    assert "confirmed_operation" in caplog.text
    assert '"kind": "confirmed"' in caplog.text
    assert '"kind": "confirmed_send"' in caplog.text
    assert '"operation": "delete campaign"' in caplog.text
    assert '"operation": "send campaign"' in caplog.text


@pytest.mark.asyncio
async def test_audit_logs_redact_pii_and_raw_queries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(server, "get_client", lambda: FakeSideEffectClient())
    server._bulk_query_events.clear()

    with caplog.at_level("WARNING", logger="listmonk_mcp.audit"):
        await server.delete_subscribers_by_query(
            query="subscribers.email = 'secret@example.com'",
            confirm=True,
        )
        await server.send_transactional_email(
            template_id=1,
            subscriber_email="secret@example.com",
            confirm_send=True,
        )

    assert "secret@example.com" not in caplog.text
    assert "subscribers.email" not in caplog.text
    assert '"sha256"' in caplog.text
    assert "<redacted-email>" in caplog.text


@pytest.mark.asyncio
async def test_bulk_query_operations_are_rate_limited_and_observable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(server, "get_client", lambda: FakeSideEffectClient())
    monkeypatch.setenv("LISTMONK_MCP_BULK_QUERY_RATE_LIMIT_PER_MINUTE", "1")
    server._bulk_query_events.clear()

    with caplog.at_level("INFO", logger="listmonk_mcp.operations"):
        first = await server.delete_subscribers_by_query(
            query="subscribers.email LIKE '%@example.com'", confirm=True
        )
        second = await server.delete_subscribers_by_query(
            query="subscribers.status = 'enabled'", confirm=True
        )

    assert first["success"] is True
    assert second["success"] is False
    assert second["error"]["error_type"] == "RateLimitExceeded"
    assert "bulk_query_operation_allowed" in caplog.text
    assert "bulk_query_rate_limited" in caplog.text


@pytest.mark.asyncio
async def test_read_only_tools_are_explicitly_annotated() -> None:
    read_only_tools = {
        "check_listmonk_health",
        "get_server_config",
        "get_i18n_language",
        "get_dashboard_charts",
        "get_dashboard_counts",
        "get_settings",
        "get_logs",
        "get_subscribers",
        "get_subscriber",
        "get_subscriber_export",
        "get_subscriber_bounces",
        "get_bounces",
        "get_bounce",
        "get_mailing_lists",
        "get_public_mailing_lists",
        "get_mailing_list",
        "get_import_subscribers",
        "get_import_subscriber_logs",
        "get_list_subscribers_tool",
        "get_campaigns",
        "get_campaign",
        "get_campaign_html_preview",
        "preview_campaign_body",
        "preview_campaign_text",
        "get_running_campaign_stats",
        "get_campaign_analytics",
        "get_templates",
        "get_template",
        "preview_template",
        "get_template_html_preview",
        "get_media_list",
        "get_media_file",
    }
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    assert all(tool.annotations is not None for tool in tools.values())
    for tool_name in read_only_tools:
        tool = tools[tool_name]
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True


def test_success_response() -> None:
    assert server.success_response("Done", resource_id=42) == {
        "success": True,
        "message": "Done",
        "resource_id": 42,
    }


def test_collection_response() -> None:
    assert server.collection_response(
        "subscribers",
        [{"id": 1}],
        total=10,
        page=2,
        per_page=1,
    ) == {
        "success": True,
        "resource": "subscribers",
        "count": 1,
        "items": [{"id": 1}],
        "total": 10,
        "page": 2,
        "per_page": 1,
    }


@pytest.mark.asyncio
async def test_get_list_subscribers_tool_returns_subscribers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_client", lambda: FakeListmonkClient())

    result = await server.get_list_subscribers_tool(list_id=7, page=2, per_page=10)

    assert result == {
        "success": True,
        "list_id": 7,
        "page": 2,
        "per_page": 10,
        "count": 2,
        "total": 2,
        "subscribers": [
            {
                "id": 1,
                "email": "ada@example.com",
                "name": "Ada Lovelace",
                "status": "enabled",
            },
            {
                "id": 2,
                "email": "grace@example.com",
                "name": "Grace Hopper",
                "status": "enabled",
            },
        ],
    }


@pytest.mark.asyncio
async def test_safe_execute_async_returns_structured_api_errors() -> None:
    async def failing_tool() -> None:
        raise ListmonkAPIError("connection failed")

    result = await safe_execute_async(failing_tool)

    assert result == {
        "success": False,
        "error": {
            "error_type": "APIError",
            "message": "connection failed",
        },
    }


@pytest.mark.asyncio
async def test_safe_execute_async_does_not_return_traceback() -> None:
    async def failing_tool() -> None:
        raise RuntimeError("boom")

    result = await safe_execute_async(failing_tool)

    assert result["success"] is False
    assert result["error"]["error_type"] == "OperationError"
    assert result["error"]["message"] == "Unexpected error while executing MCP tool"
    assert result["error"]["operation"] == "failing_tool"
    assert result["error"]["details"] == {"error": "boom"}
    assert "Traceback" not in str(result)
