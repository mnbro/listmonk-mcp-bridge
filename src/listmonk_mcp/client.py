"""Async Listmonk HTTP client used by MCP tools."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
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


def normalize_rfc3339_date(value: str) -> str:
    """Expand a date-only maintenance cutoff to Listmonk's RFC3339 format."""

    if len(value) == 10:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            pass
        else:
            return f"{value}T00:00:00Z"
    return value


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


def extract_related_ids(payload: dict[str, Any], field: str) -> list[int]:
    """Extract integer IDs from Listmonk relationship arrays."""

    ids: list[int] = []
    for item in payload.get(field) or []:
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


def extract_bounce_campaign_id(bounce: dict[str, Any]) -> int | None:
    """Extract a campaign ID from Listmonk's nested bounce representation."""

    campaign_id = bounce.get("campaign_id")
    if isinstance(campaign_id, int) and not isinstance(campaign_id, bool):
        return campaign_id
    campaign = bounce.get("campaign")
    if isinstance(campaign, str):
        try:
            campaign = json.loads(campaign)
        except json.JSONDecodeError:
            return None
    if isinstance(campaign, dict):
        value = campaign.get("id")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def response_object(response: dict[str, Any], resource: str) -> dict[str, Any]:
    """Return a single Listmonk response object or fail with a useful error."""

    data = response.get("data")
    if not isinstance(data, dict):
        raise ListmonkAPIError(f"Listmonk returned no {resource} object")
    return data


def campaign_update_payload(
    campaign: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    """Build Listmonk's full campaign PUT payload without losing relationships."""

    template = campaign.get("template")
    template_id = campaign.get("template_id")
    if template_id is None and isinstance(template, dict):
        template_id = template.get("id")

    payload = {
        "name": campaign.get("name"),
        "subject": campaign.get("subject"),
        "lists": extract_related_ids(campaign, "lists"),
        "from_email": campaign.get("from_email"),
        "body": campaign.get("body"),
        "altbody": campaign.get("altbody"),
        "content_type": campaign.get("content_type"),
        "send_at": campaign.get("send_at"),
        "headers": campaign.get("headers") or [],
        "attribs": campaign.get("attribs") or {},
        "tags": campaign.get("tags") or [],
        "messenger": campaign.get("messenger"),
        "template_id": template_id,
        "archive": campaign.get("archive", False),
        "archive_slug": campaign.get("archive_slug"),
        "archive_template_id": campaign.get("archive_template_id"),
        "archive_meta": campaign.get("archive_meta") or {},
        "media": extract_related_ids(campaign, "media"),
        "body_source": campaign.get("body_source"),
    }
    payload.update(overrides)
    return payload


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
        safe_to_retry = method.upper() in {"GET", "HEAD", "OPTIONS"}
        try:
            response = await client.request(
                method,
                self._build_url(endpoint),
                params=params,
                json=json_data,
            )
        except httpx.RequestError as exc:
            if safe_to_retry and retry_count < self.config.max_retries:
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

    async def get_about(self) -> dict[str, Any]:
        return await self._request("GET", "/api/about")

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
        attribs: dict[str, Any] | None = None,
        preconfirm_subscriptions: bool | None = None,
    ) -> dict[str, Any]:
        payload = compact_payload(
            {
                "email": email,
                "name": name,
                "status": status,
                "lists": lists,
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
            "PUT", "/api/subscribers/query/blocklist", json_data={"query": query}
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
        source: str | None = None,
    ) -> dict[str, Any]:
        if subscriber_id is not None:
            response = await self.get_subscriber_bounces(subscriber_id)
            data = response.get("data")
            raw_results = (
                data.get("results", [])
                if isinstance(data, dict)
                else data
                if isinstance(data, list)
                else []
            )
            results = [item for item in raw_results if isinstance(item, dict)]
            if campaign_id is not None:
                results = [
                    item
                    for item in results
                    if extract_bounce_campaign_id(item) == campaign_id
                ]
            if source is not None:
                results = [item for item in results if item.get("source") == source]
            results.sort(
                key=lambda item: str(item.get(order_by) or ""),
                reverse=order == "desc",
            )
            total = len(results)
            start = max(page - 1, 0) * per_page
            return {
                "data": {
                    "results": results[start : start + per_page],
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                }
            }
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
                    "source": source,
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
        current = response_object(await self.get_list(list_id), "list")
        payload = {
            "name": current.get("name"),
            "type": current.get("type"),
            "optin": current.get("optin"),
            "tags": current.get("tags") or [],
            "description": current.get("description") or "",
        }
        payload.update(
            compact_payload(
                {
                    "name": name,
                    "type": type,
                    "optin": optin,
                    "tags": tags,
                    "description": description,
                }
            )
        )
        return await self._request(
            "PUT",
            f"/api/lists/{list_id}",
            json_data=payload,
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
                data={"params": json.dumps(params, separators=(",", ":"))},
                files={"file": (path.name, handle, "text/csv")},
            )

    async def get_list_subscribers(
        self, list_id: int, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        return await self.get_subscribers(
            page=page,
            per_page=per_page,
            list_ids=[list_id],
        )

    async def get_campaigns(
        self,
        page: int = 1,
        per_page: int = 20,
        order_by: str = "created_at",
        order: str = "desc",
        status: str | list[str] | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        no_body: bool | None = None,
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
                    "tag": tags,
                    "query": query,
                    "no_body": no_body,
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
                "send_at": send_at,
                "messenger": messenger,
                "headers": headers,
            }
        )
        return await self._request("POST", "/api/campaigns", json_data=payload)

    async def update_campaign(self, campaign_id: int, **fields: Any) -> dict[str, Any]:
        current = response_object(await self.get_campaign(campaign_id), "campaign")
        return await self._request(
            "PUT",
            f"/api/campaigns/{campaign_id}",
            json_data=campaign_update_payload(current, fields),
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
            "PUT",
            f"/api/campaigns/{campaign_id}/status",
            json_data={"status": "running"},
        )

    async def schedule_campaign(self, campaign_id: int, send_at: str) -> dict[str, Any]:
        await self.update_campaign(campaign_id, send_at=send_at)
        return await self._request(
            "PUT",
            f"/api/campaigns/{campaign_id}/status",
            json_data={"status": "scheduled"},
        )

    async def update_campaign_status(
        self, campaign_id: int, status: str
    ) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/api/campaigns/{campaign_id}/status", json_data={"status": status}
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
        return await self._request_form(
            "POST",
            f"/api/campaigns/{campaign_id}/preview",
            data=compact_payload(
                {"body": body, "content_type": content_type, "template_id": template_id}
            ),
        )

    async def preview_campaign_text(
        self, campaign_id: int, body: str, content_type: str = "plain"
    ) -> dict[str, Any]:
        return await self._request_form(
            "POST",
            f"/api/campaigns/{campaign_id}/text",
            data={"body": body, "content_type": content_type},
        )

    async def get_running_campaign_stats(
        self, campaign_ids: list[int]
    ) -> dict[str, Any]:
        response = await self._request("GET", "/api/campaigns/running/stats")
        data = response.get("data")
        if isinstance(data, list):
            requested = set(campaign_ids)
            response = {
                **response,
                "data": [
                    item
                    for item in data
                    if isinstance(item, dict) and item.get("id") in requested
                ],
            }
        return response

    async def get_campaign_analytics(
        self,
        campaign_id: int,
        type: str = "views",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        start = from_date or "1970-01-01"
        end = to_date or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        return await self._request(
            "GET",
            f"/api/campaigns/analytics/{type}",
            params={"id": campaign_id, "from": start, "to": end},
        )

    async def archive_campaign(
        self, campaign_id: int, archive: bool = True
    ) -> dict[str, Any]:
        campaign = response_object(await self.get_campaign(campaign_id), "campaign")
        return await self._request(
            "PUT",
            f"/api/campaigns/{campaign_id}/archive",
            json_data={
                "archive": archive,
                "archive_template_id": campaign.get("archive_template_id"),
                "archive_meta": campaign.get("archive_meta") or {},
                "archive_slug": campaign.get("archive_slug") or "",
            },
        )

    async def convert_campaign_content(
        self, campaign_id: int, editor: str
    ) -> dict[str, Any]:
        campaign = response_object(await self.get_campaign(campaign_id), "campaign")
        return await self._request(
            "POST",
            f"/api/campaigns/{campaign_id}/content",
            json_data={
                "id": campaign_id,
                "body": campaign.get("body") or "",
                "from": campaign.get("content_type"),
                "to": editor,
            },
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
        response = await self._request(
            "POST",
            "/api/templates",
            json_data=compact_payload(
                {
                    "name": name,
                    "subject": subject,
                    "body": body,
                    "type": type,
                    "body_source": body_source,
                }
            ),
        )
        if not is_default:
            return response
        template = response_object(response, "template")
        template_id = template.get("id")
        if not isinstance(template_id, int) or isinstance(template_id, bool):
            raise ListmonkAPIError("Listmonk returned no template ID")
        await self.set_default_template(template_id)
        return await self.get_template(template_id)

    async def update_template(self, template_id: int, **fields: Any) -> dict[str, Any]:
        current = response_object(await self.get_template(template_id), "template")
        requested_type = fields.pop("type", None)
        if requested_type is not None and requested_type != current.get("type"):
            raise ListmonkAPIError(
                "Listmonk does not support changing an existing template's type"
            )
        requested_default = fields.pop("is_default", None)
        if requested_default is False and current.get("is_default") is True:
            raise ListmonkAPIError(
                "Listmonk cannot unset a default template without selecting another default"
            )
        payload = {
            "name": current.get("name"),
            "subject": current.get("subject") or "",
            "body": current.get("body") or "",
            "type": current.get("type"),
            "body_source": current.get("body_source"),
        }
        payload.update(compact_payload(fields))
        response = await self._request(
            "PUT", f"/api/templates/{template_id}", json_data=payload
        )
        if requested_default is True and current.get("is_default") is not True:
            await self.set_default_template(template_id)
            return await self.get_template(template_id)
        return response

    async def delete_template(self, template_id: int) -> dict[str, Any]:
        return await self._request("DELETE", f"/api/templates/{template_id}")

    async def preview_template(
        self, template_id: int, body: str
    ) -> dict[str, Any]:
        template = response_object(await self.get_template(template_id), "template")
        return await self._request_form(
            "POST",
            "/api/templates/preview",
            data={"body": body, "template_type": template.get("type") or "campaign"},
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

    async def get_media(
        self, page: int = 1, per_page: int = 20, query: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/media",
            params=compact_payload(
                {"page": page, "per_page": per_page, "query": query}
            ),
        )

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
                data={},
                files={"file": (title or path.name, handle)},
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
        return await self._request_form(
            "DELETE",
            f"/api/maintenance/analytics/{type}",
            data={"before_date": normalize_rfc3339_date(before_date)},
        )

    async def delete_unconfirmed_subscriptions(
        self, before_date: str
    ) -> dict[str, Any]:
        return await self._request_form(
            "DELETE",
            "/api/maintenance/subscriptions/unconfirmed",
            data={"before_date": normalize_rfc3339_date(before_date)},
        )
