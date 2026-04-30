"""Async Listmonk HTTP client used by MCP tools."""

from __future__ import annotations

import asyncio
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from . import __version__
from .config import Config


def normalize_body(
    body: str,
    content_type: str,
    auto_convert_plain_to_html: bool = True,
) -> tuple[str, str]:
    """Convert plain text campaign bodies to simple escaped HTML paragraphs."""

    if content_type != "plain" or not auto_convert_plain_to_html:
        return body, content_type
    paragraphs = [
        f"<p>{escape(part).replace(chr(10), '<br>')}</p>" for part in body.split("\n\n")
    ]
    return "".join(paragraphs), "html"


def compact_payload(values: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None while preserving falsey user values."""

    return {key: value for key, value in values.items() if value is not None}


def listmonk_query_string_literal(value: str) -> str:
    """Return a single-quoted Listmonk query string literal."""

    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def extract_campaign_list_ids(campaign: dict[str, Any]) -> list[int]:
    """Extract list IDs from Listmonk campaign payloads."""

    ids: list[int] = []
    for item in campaign.get("lists") or []:
        value: Any
        if isinstance(item, dict):
            value = item.get("id")
        else:
            value = item
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            ids.append(value)
        elif isinstance(value, str) and value.isdigit():
            ids.append(int(value))
    return ids


def campaign_test_payload(
    campaign: dict[str, Any], subscribers: list[str]
) -> dict[str, Any]:
    """Build the payload Listmonk expects for campaign test sends."""

    template = campaign.get("template")
    template_id = campaign.get("template_id")
    if template_id is None and isinstance(template, dict):
        template_id = template.get("id")
    return compact_payload(
        {
            "name": campaign.get("name"),
            "subject": campaign.get("subject"),
            "lists": extract_campaign_list_ids(campaign),
            "type": campaign.get("type"),
            "from_email": campaign.get("from_email"),
            "body": campaign.get("body"),
            "content_type": campaign.get("content_type"),
            "altbody": campaign.get("altbody"),
            "template_id": template_id,
            "tags": campaign.get("tags"),
            "messenger": campaign.get("messenger"),
            "headers": campaign.get("headers"),
            "subscribers": subscribers,
        }
    )


class ListmonkAPIError(Exception):
    """Raised when Listmonk returns an error or cannot be reached."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ListmonkClient:
    """Small async wrapper around the Listmonk HTTP API."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = config.url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ListmonkClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Create the underlying HTTP client if needed."""

        if self._client is not None:
            return
        self._client = httpx.AsyncClient(
            timeout=self.config.timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "Accept": "application/json",
                "Authorization": f"token {self.config.username}:{self.config.password}",
                "Content-Type": "application/json",
                "User-Agent": f"listmonk-mcp-bridge/{__version__}",
            },
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            await self.connect()
        if self._client is None:
            raise RuntimeError("HTTP client was not initialized")
        return self._client

    def _build_url(self, endpoint: str) -> str:
        return urljoin(f"{self.base_url}/", endpoint.lstrip("/"))

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.request(
                method,
                self._build_url(endpoint),
                params=params,
                json=json_data,
            )
        except httpx.RequestError as exc:
            if retry_count < self.config.max_retries:
                await asyncio.sleep(min(2**retry_count, 8))
                return await self._request(
                    method, endpoint, params, json_data, retry_count + 1
                )
            raise ListmonkAPIError(f"Request failed: {exc}") from exc
        return await self._handle_response(response)

    async def _request_form(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.request(
                method,
                self._build_url(endpoint),
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.RequestError as exc:
            raise ListmonkAPIError(f"Request failed: {exc}") from exc
        return await self._handle_response(response)

    async def _request_files(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, Any],
        files: dict[str, Any],
    ) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.request(
                method, self._build_url(endpoint), data=data, files=files
            )
        except httpx.RequestError as exc:
            raise ListmonkAPIError(f"Request failed: {exc}") from exc
        return await self._handle_response(response)

    async def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {"text": response.text}
        if response.is_success:
            return payload if isinstance(payload, dict) else {"data": payload}
        message = str(
            payload.get("message")
            or payload.get("error")
            or f"HTTP {response.status_code}"
        )
        raise ListmonkAPIError(
            message, status_code=response.status_code, response=payload
        )

    async def health_check(self) -> dict[str, Any]:
        return await self._request("GET", "/api/health")

    async def get_server_config(self) -> dict[str, Any]:
        return await self._request("GET", "/api/config")

    async def get_i18n_language(self, lang: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/lang/{lang}")

    async def get_dashboard_charts(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dashboard/charts")

    async def get_dashboard_counts(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dashboard/counts")

    async def get_settings(self) -> dict[str, Any]:
        return await self._request("GET", "/api/settings")

    async def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", "/api/settings", json_data=settings)

    async def test_smtp_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/settings/smtp/test", json_data=settings
        )

    async def reload_app(self) -> dict[str, Any]:
        return await self._request("POST", "/api/admin/reload")

    async def get_logs(self) -> dict[str, Any]:
        return await self._request("GET", "/api/logs")

    async def get_subscribers(
        self,
        page: int = 1,
        per_page: int | str = 20,
        order_by: str = "created_at",
        order: str = "desc",
        query: str | None = None,
        subscription_status: str | None = None,
        list_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        params = compact_payload(
            {
                "page": page,
                "per_page": per_page,
                "order_by": order_by,
                "order": order,
                "query": query,
                "subscription_status": subscription_status,
                "list_id": list_ids,
            }
        )
        return await self._request("GET", "/api/subscribers", params=params)

    async def get_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/subscribers/{subscriber_id}")

    async def get_subscriber_by_email(self, email: str) -> dict[str, Any]:
        data = await self.get_subscribers(
            query=f"subscribers.email = {listmonk_query_string_literal(email)}"
        )
        results = data.get("data", {}).get("results", [])
        return {"data": results[0] if results else None}

    async def create_subscriber(
        self,
        email: str,
        name: str,
        status: str = "enabled",
        lists: list[int] | None = None,
        attribs: dict[str, Any] | None = None,
        preconfirm_subscriptions: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/subscribers",
            json_data={
                "email": email,
                "name": name,
                "status": status,
                "lists": lists or [],
                "attribs": attribs or {},
                "preconfirm_subscriptions": preconfirm_subscriptions,
            },
        )

    async def update_subscriber(
        self,
        subscriber_id: int,
        email: str | None = None,
        name: str | None = None,
        status: str | None = None,
        lists: list[int] | None = None,
        list_uuids: list[str] | None = None,
        attribs: dict[str, Any] | None = None,
        preconfirm_subscriptions: bool | None = None,
    ) -> dict[str, Any]:
        payload = compact_payload(
            {
                "email": email,
                "name": name,
                "status": status,
                "lists": lists,
                "list_uuids": list_uuids,
                "attribs": attribs,
                "preconfirm_subscriptions": preconfirm_subscriptions,
            }
        )
        return await self._request(
            "PATCH", f"/api/subscribers/{subscriber_id}", json_data=payload
        )

    async def delete_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/subscribers/{subscriber_id}")

    async def delete_subscribers(self, subscriber_ids: list[int]) -> dict[str, Any]:
        return await self._request(
            "DELETE", "/api/subscribers", params={"id": subscriber_ids}
        )

    async def send_subscriber_optin(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/subscribers/{subscriber_id}/optin")

    async def get_subscriber_export(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/subscribers/{subscriber_id}/export")

    async def get_subscriber_bounces(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/subscribers/{subscriber_id}/bounces")

    async def delete_subscriber_bounces(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request(
            "DELETE", f"/api/subscribers/{subscriber_id}/bounces"
        )

    async def set_subscriber_status(
        self, subscriber_id: int, status: str
    ) -> dict[str, Any]:
        return await self.update_subscriber(subscriber_id, status=status)

    async def blocklist_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        return await self._request("PUT", f"/api/subscribers/{subscriber_id}/blocklist")

    async def blocklist_subscribers(
        self,
        ids: list[int] | None = None,
        subscriber_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/api/subscribers/blocklist",
            json_data={"ids": ids if ids is not None else subscriber_ids or []},
        )

    async def delete_subscribers_by_query(self, query: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/subscribers/query/delete", json_data={"query": query}
        )

    async def blocklist_subscribers_by_query(self, query: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/subscribers/query/blocklist", json_data={"query": query}
        )

    async def manage_subscriber_lists_by_query(
        self,
        query: str,
        action: str,
        target_list_ids: list[int],
        status: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/api/subscribers/query/lists",
            json_data=compact_payload(
                {
                    "query": query,
                    "action": action,
                    "target_list_ids": target_list_ids,
                    "status": status,
                }
            ),
        )

    async def manage_subscriber_lists(
        self,
        action: str,
        target_list_ids: list[int],
        ids: list[int] | None = None,
        subscriber_ids: list[int] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            "/api/subscribers/lists",
            json_data=compact_payload(
                {
                    "action": action,
                    "target_list_ids": target_list_ids,
                    "ids": ids if ids is not None else subscriber_ids,
                    "status": status,
                }
            ),
        )

    async def get_bounces(
        self,
        page: int = 1,
        per_page: int = 20,
        order_by: str = "created_at",
        order: str = "desc",
        campaign_id: int | None = None,
        subscriber_id: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/bounces",
            params=compact_payload(
                {
                    "page": page,
                    "per_page": per_page,
                    "order_by": order_by,
                    "order": order,
                    "campaign_id": campaign_id,
                    "subscriber_id": subscriber_id,
                }
            ),
        )

    async def get_bounce(self, bounce_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/bounces/{bounce_id}")

    async def delete_bounce(self, bounce_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/bounces/{bounce_id}")

    async def delete_bounces(
        self,
        bounce_ids: list[int] | None = None,
        all: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE", "/api/bounces", params={"all": all, "id": bounce_ids or []}
        )

    async def get_lists(
        self,
        page: int = 1,
        per_page: int = 20,
        order_by: str = "created_at",
        order: str = "desc",
        query: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/lists",
            params=compact_payload(
                {
                    "page": page,
                    "per_page": per_page,
                    "order_by": order_by,
                    "order": order,
                    "query": query,
                }
            ),
        )

    async def get_public_lists(self) -> dict[str, Any]:
        return await self._request("GET", "/api/public/lists")

    async def get_list(self, list_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/lists/{list_id}")

    async def create_list(
        self,
        name: str,
        type: str = "public",
        optin: str = "single",
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/lists",
            json_data=compact_payload(
                {
                    "name": name,
                    "type": type,
                    "optin": optin,
                    "tags": tags or [],
                    "description": description,
                }
            ),
        )

    async def update_list(
        self,
        list_id: int,
        name: str | None = None,
        type: str | None = None,
        optin: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/api/lists/{list_id}",
            json_data=compact_payload(
                {
                    "name": name,
                    "type": type,
                    "optin": optin,
                    "tags": tags,
                    "description": description,
                }
            ),
        )

    async def delete_list(self, list_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/lists/{list_id}")

    async def delete_lists(
        self, ids: list[int] | None = None, list_ids: list[int] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            "/api/lists",
            params={"id": ids if ids is not None else list_ids or []},
        )

    async def get_import_subscribers(self) -> dict[str, Any]:
        return await self._request("GET", "/api/import/subscribers")

    async def get_import_subscriber_logs(self) -> dict[str, Any]:
        return await self._request("GET", "/api/import/subscribers/logs")

    async def stop_import_subscribers(self) -> dict[str, Any]:
        return await self._request("DELETE", "/api/import/subscribers")

    async def import_subscribers(
        self, file_path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        path = Path(file_path)
        with path.open("rb") as handle:
            return await self._request_files(
                "POST",
                "/api/import/subscribers",
                data={key: str(value) for key, value in params.items()},
                files={"file": (path.name, handle, "text/csv")},
            )

    async def get_list_subscribers(
        self, list_id: int, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/lists/{list_id}/subscribers",
            params={"page": page, "per_page": per_page},
        )

    async def get_campaigns(
        self,
        page: int = 1,
        per_page: int = 20,
        order_by: str = "created_at",
        order: str = "desc",
        status: str | None = None,
        type: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/campaigns",
            params=compact_payload(
                {
                    "page": page,
                    "per_page": per_page,
                    "order_by": order_by,
                    "order": order,
                    "status": status,
                    "type": type,
                }
            ),
        )

    async def get_campaign(
        self, campaign_id: int, no_body: bool | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/campaigns/{campaign_id}",
            params=compact_payload({"no_body": no_body}),
        )

    async def create_campaign(
        self,
        name: str,
        subject: str,
        lists: list[int],
        type: str = "regular",
        from_email: str | None = None,
        body: str | None = None,
        content_type: str = "richtext",
        altbody: str | None = None,
        template_id: int | None = None,
        tags: list[str] | None = None,
        send_later: bool | None = None,
        send_at: str | None = None,
        messenger: str | None = None,
        headers: list[dict[str, Any]] | None = None,
        auto_convert_plain_to_html: bool = True,
    ) -> dict[str, Any]:
        if body is not None:
            body, content_type = normalize_body(
                body, content_type, auto_convert_plain_to_html
            )
        payload = compact_payload(
            {
                "name": name,
                "subject": subject,
                "lists": lists,
                "type": type,
                "from_email": from_email,
                "body": body,
                "content_type": content_type,
                "altbody": altbody,
                "template_id": template_id,
                "tags": tags or [],
                "send_later": send_later,
                "send_at": send_at,
                "messenger": messenger,
                "headers": headers,
            }
        )
        return await self._request("POST", "/api/campaigns", json_data=payload)

    async def update_campaign(self, campaign_id: int, **fields: Any) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/api/campaigns/{campaign_id}", json_data=compact_payload(fields)
        )

    async def delete_campaign(self, campaign_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/campaigns/{campaign_id}")

    async def delete_campaigns(
        self, ids: list[int] | None = None, campaign_ids: list[int] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            "/api/campaigns",
            params={"id": ids if ids is not None else campaign_ids or []},
        )

    async def send_campaign(self, campaign_id: int) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/status",
            json_data={"status": "running"},
        )

    async def schedule_campaign(self, campaign_id: int, send_at: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/status",
            json_data={"status": "scheduled", "send_at": send_at},
        )

    async def update_campaign_status(
        self, campaign_id: int, status: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST", f"/api/campaigns/{campaign_id}/status", json_data={"status": status}
        )

    async def get_campaign_preview(self, campaign_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/campaigns/{campaign_id}/preview")

    async def preview_campaign_body(
        self,
        campaign_id: int,
        body: str,
        content_type: str = "html",
        template_id: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/preview",
            json_data=compact_payload(
                {"body": body, "content_type": content_type, "template_id": template_id}
            ),
        )

    async def preview_campaign_text(
        self, campaign_id: int, body: str, content_type: str = "plain"
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/text",
            json_data={"body": body, "content_type": content_type},
        )

    async def get_running_campaign_stats(
        self, campaign_ids: list[int]
    ) -> dict[str, Any]:
        return await self._request(
            "GET", "/api/campaigns/running/stats", params={"id": campaign_ids}
        )

    async def get_campaign_analytics(
        self,
        campaign_id: int,
        type: str = "views",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/campaigns/{campaign_id}/analytics/{type}",
            params=compact_payload({"from": from_date, "to": to_date}),
        )

    async def archive_campaign(
        self, campaign_id: int, archive: bool = True
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/api/campaigns/{campaign_id}/archive",
            json_data={"archive": archive},
        )

    async def convert_campaign_content(
        self, campaign_id: int, editor: str
    ) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/api/campaigns/{campaign_id}/content/{editor}"
        )

    async def test_campaign(
        self, campaign_id: int, subscribers: list[str]
    ) -> dict[str, Any]:
        response = await self.get_campaign(campaign_id)
        campaign = response.get("data", {})
        if not isinstance(campaign, dict):
            campaign = {}
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/test",
            json_data=campaign_test_payload(campaign, subscribers),
        )

    async def get_templates(self, no_body: bool | None = None) -> dict[str, Any]:
        return await self._request(
            "GET", "/api/templates", params=compact_payload({"no_body": no_body})
        )

    async def get_template(
        self, template_id: int, no_body: bool | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/api/templates/{template_id}",
            params=compact_payload({"no_body": no_body}),
        )

    async def create_template(
        self,
        name: str,
        subject: str,
        body: str,
        type: str = "campaign",
        is_default: bool = False,
        body_source: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/templates",
            json_data=compact_payload(
                {
                    "name": name,
                    "subject": subject,
                    "body": body,
                    "type": type,
                    "is_default": is_default,
                    "body_source": body_source,
                }
            ),
        )

    async def update_template(self, template_id: int, **fields: Any) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/api/templates/{template_id}", json_data=compact_payload(fields)
        )

    async def delete_template(self, template_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/templates/{template_id}")

    async def preview_template(
        self, template_id: int, body: str, content_type: str = "html"
    ) -> dict[str, Any]:
        return await self._request_form(
            "POST",
            f"/api/templates/{template_id}/preview",
            data={"body": body, "content_type": content_type},
        )

    async def get_template_preview(self, template_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/templates/{template_id}/preview")

    async def set_default_template(self, template_id: int) -> dict[str, Any]:
        return await self._request("PUT", f"/api/templates/{template_id}/default")

    async def send_transactional_email(self, **kwargs: Any) -> dict[str, Any]:
        payload = {"content_type": "html", **kwargs}
        return await self._request(
            "POST", "/api/tx", json_data=compact_payload(payload)
        )

    async def get_media(self) -> dict[str, Any]:
        return await self._request("GET", "/api/media")

    async def get_media_file(self, media_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/media/{media_id}")

    async def upload_media(
        self, file_path: str, title: str | None = None
    ) -> dict[str, Any]:
        path = Path(file_path)
        with path.open("rb") as handle:
            return await self._request_files(
                "POST",
                "/api/media",
                data=compact_payload({"title": title}),
                files={"file": (path.name, handle)},
            )

    async def update_media(self, media_id: int, title: str) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/api/media/{media_id}", json_data={"title": title}
        )

    async def delete_media(self, media_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/media/{media_id}")

    async def create_public_subscription(
        self, name: str, email: str, list_uuids: list[str]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/public/subscription",
            json_data={"name": name, "email": email, "list_uuids": list_uuids},
        )

    async def delete_gc_subscribers(self, type: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/maintenance/subscribers/{type}")

    async def delete_campaign_analytics(
        self, type: str, before_date: str
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"/api/maintenance/analytics/{type}",
            json_data={"before_date": before_date},
        )

    async def delete_unconfirmed_subscriptions(
        self, before_date: str
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            "/api/maintenance/subscriptions/unconfirmed",
            json_data={"before_date": before_date},
        )
