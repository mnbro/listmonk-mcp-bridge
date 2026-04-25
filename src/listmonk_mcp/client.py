"""Listmonk API client abstraction using httpx."""

import asyncio
import json
from html import escape
from typing import Any
from urllib.parse import urljoin

import httpx
from httpx import AsyncClient, Response

from .config import Config


def normalize_body(
    body: str,
    content_type: str,
    auto_convert_plain_to_html: bool = True,
) -> tuple[str, str]:
    """Normalize campaign body content before sending it to Listmonk."""
    if content_type != "plain" or not auto_convert_plain_to_html:
        return body, content_type

    paragraphs = []
    for raw_paragraph in body.split("\n\n"):
        escaped = escape(raw_paragraph).replace("\n", "<br>")
        paragraphs.append(f"<p>{escaped}</p>")

    return "".join(paragraphs), "html"


class ListmonkAPIError(Exception):
    """Base exception for Listmonk API errors."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ListmonkClient:
    """Async HTTP client for Listmonk API operations."""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.url.rstrip('/')
        self._client: AsyncClient | None = None

    async def __aenter__(self) -> "ListmonkClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Initialize the HTTP client with authentication."""
        # Use API token authentication format: "username:token"
        auth_token = f"{self.config.username}:{self.config.password}"

        self._client = AsyncClient(
            timeout=self.config.timeout,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            headers={
                "User-Agent": "Listmonk-MCP-Server/0.1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"token {auth_token}"
            }
        )

        # Test connection with health check
        await self.health_check()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> AsyncClient:
        """Get the HTTP client, raising error if not connected."""
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first or use as async context manager.")
        return self._client

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        return urljoin(f"{self.base_url}/", endpoint.lstrip('/'))

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retry_count: int = 0
    ) -> dict[str, Any]:
        """Make HTTP request with retry logic and error handling."""
        client = self._get_client()
        url = self._build_url(endpoint)

        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data
            )

            return await self._handle_response(response)

        except httpx.RequestError as e:
            if retry_count < self.config.max_retries:
                await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                return await self._request(method, endpoint, params, json_data, retry_count + 1)

            raise ListmonkAPIError(f"Request failed: {str(e)}") from e

    async def _handle_response(self, response: Response) -> dict[str, Any]:
        """Handle HTTP response and extract data."""
        try:
            response_data = response.json()
        except Exception:
            response_data = {"text": response.text}

        if response.is_success:
            return response_data  # type: ignore[no-any-return]

        # Handle API errors
        error_message = response_data.get("message", f"HTTP {response.status_code}")
        raise ListmonkAPIError(
            message=error_message,
            status_code=response.status_code,
            response=response_data
        )

    async def _request_form(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a form-encoded HTTP request."""
        client = self._get_client()
        url = self._build_url(endpoint)

        try:
            response = await client.request(
                method=method,
                url=url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return await self._handle_response(response)
        except httpx.RequestError as e:
            raise ListmonkAPIError(f"Request failed: {str(e)}") from e

    # Health and Authentication
    async def health_check(self) -> dict[str, Any]:
        """Check if Listmonk server is healthy and accessible."""
        return await self._request("GET", "/api/health")

    async def get_server_config(self) -> dict[str, Any]:
        """Get general server config."""
        return await self._request("GET", "/api/config")

    async def get_i18n_language(self, lang: str) -> dict[str, Any]:
        """Get an i18n language pack."""
        return await self._request("GET", f"/api/lang/{lang}")

    async def get_dashboard_charts(self) -> dict[str, Any]:
        """Get dashboard chart data."""
        return await self._request("GET", "/api/dashboard/charts")

    async def get_dashboard_counts(self) -> dict[str, Any]:
        """Get dashboard count data."""
        return await self._request("GET", "/api/dashboard/counts")

    async def get_settings(self) -> dict[str, Any]:
        """Get Listmonk settings."""
        return await self._request("GET", "/api/settings")

    async def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Update Listmonk settings."""
        return await self._request("PUT", "/api/settings", json_data=settings)

    async def test_smtp_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Test SMTP settings."""
        return await self._request("POST", "/api/settings/smtp/test", json_data=settings)

    async def reload_app(self) -> dict[str, Any]:
        """Reload the Listmonk app."""
        return await self._request("POST", "/api/admin/reload")

    async def get_logs(self) -> dict[str, Any]:
        """Get buffered Listmonk logs."""
        return await self._request("GET", "/api/logs")

    # Subscriber Operations
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
        """Get subscribers with pagination and filtering."""
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "order_by": order_by,
            "order": order,
        }
        if query:
            params["query"] = query
        if subscription_status is not None:
            params["subscription_status"] = subscription_status
        if list_ids is not None:
            params["list_id"] = list_ids

        return await self._request("GET", "/api/subscribers", params=params)

    async def get_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        """Get subscriber by ID."""
        return await self._request("GET", f"/api/subscribers/{subscriber_id}")

    async def get_subscriber_by_email(self, email: str) -> dict[str, Any]:
        """Get subscriber by email address."""
        params = {"query": f"subscribers.email = '{email}'"}
        response = await self._request("GET", "/api/subscribers", params=params)

        if response.get("data", {}).get("results"):
            return {"data": response["data"]["results"][0]}
        else:
            raise ListmonkAPIError(f"Subscriber with email {email} not found", status_code=404)

    async def create_subscriber(
        self,
        email: str,
        name: str,
        status: str = "enabled",
        lists: list[int] | None = None,
        attribs: dict[str, Any] | None = None,
        preconfirm_subscriptions: bool = False
    ) -> dict[str, Any]:
        """Create a new subscriber."""
        data = {
            "email": email,
            "name": name,
            "status": status,
            "lists": lists or [],
            "attribs": attribs or {},
            "preconfirm_subscriptions": preconfirm_subscriptions
        }
        return await self._request("POST", "/api/subscribers", json_data=data)

    async def update_subscriber(
        self,
        subscriber_id: int,
        email: str | None = None,
        name: str | None = None,
        status: str | None = None,
        lists: list[int] | None = None,
        attribs: dict[str, Any] | None = None,
        list_uuids: list[str] | None = None,
        preconfirm_subscriptions: bool | None = None
    ) -> dict[str, Any]:
        """Update an existing subscriber."""
        data: dict[str, Any] = {}
        if email is not None:
            data["email"] = email
        if name is not None:
            data["name"] = name
        if status is not None:
            data["status"] = status
        if lists is not None:
            data["lists"] = lists
        if attribs is not None:
            data["attribs"] = attribs
        if list_uuids is not None:
            data["list_uuids"] = list_uuids
        if preconfirm_subscriptions is not None:
            data["preconfirm_subscriptions"] = preconfirm_subscriptions

        return await self._request("PUT", f"/api/subscribers/{subscriber_id}", json_data=data)

    async def delete_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        """Delete a subscriber."""
        return await self._request("DELETE", f"/api/subscribers/{subscriber_id}")

    async def delete_subscribers(self, subscriber_ids: list[int]) -> dict[str, Any]:
        """Delete multiple subscribers by ID."""
        return await self._request("DELETE", "/api/subscribers", params={"id": subscriber_ids})

    async def send_subscriber_optin(self, subscriber_id: int) -> dict[str, Any]:
        """Send an opt-in confirmation email to a subscriber."""
        return await self._request("POST", f"/api/subscribers/{subscriber_id}/optin")

    async def get_subscriber_export(self, subscriber_id: int) -> dict[str, Any]:
        """Export all data for a subscriber."""
        return await self._request("GET", f"/api/subscribers/{subscriber_id}/export")

    async def get_subscriber_bounces(self, subscriber_id: int) -> dict[str, Any]:
        """Get bounce records for a subscriber."""
        return await self._request("GET", f"/api/subscribers/{subscriber_id}/bounces")

    async def delete_subscriber_bounces(self, subscriber_id: int) -> dict[str, Any]:
        """Delete bounce records for a subscriber."""
        return await self._request("DELETE", f"/api/subscribers/{subscriber_id}/bounces")

    async def set_subscriber_status(self, subscriber_id: int, status: str) -> dict[str, Any]:
        """Set subscriber status (enabled, disabled, blocklisted)."""
        data = {"status": status}
        return await self._request("PUT", f"/api/subscribers/{subscriber_id}", json_data=data)

    async def blocklist_subscriber(self, subscriber_id: int) -> dict[str, Any]:
        """Blocklist a subscriber."""
        return await self._request("PUT", f"/api/subscribers/{subscriber_id}/blocklist", json_data={})

    async def blocklist_subscribers(
        self,
        ids: list[int] | None = None,
        query: str | None = None,
        action: str | None = None,
        target_list_ids: list[int] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Blocklist subscribers by IDs or query."""
        data: dict[str, Any] = {}
        if ids is not None:
            data["ids"] = ids
        if query is not None:
            data["query"] = query
        if action is not None:
            data["action"] = action
        if target_list_ids is not None:
            data["target_list_ids"] = target_list_ids
        if status is not None:
            data["status"] = status
        return await self._request("PUT", "/api/subscribers/blocklist", json_data=data)

    async def delete_subscribers_by_query(self, query: str) -> dict[str, Any]:
        """Delete subscribers matched by SQL query."""
        return await self._request("POST", "/api/subscribers/query/delete", json_data={"query": query})

    async def blocklist_subscribers_by_query(self, query: str) -> dict[str, Any]:
        """Blocklist subscribers matched by SQL query."""
        return await self._request("PUT", "/api/subscribers/query/blocklist", json_data={"query": query})

    async def manage_subscriber_lists_by_query(
        self,
        query: str,
        action: str,
        target_list_ids: list[int],
        status: str | None = None,
    ) -> dict[str, Any]:
        """Add, remove, or unsubscribe query-matched subscribers from lists."""
        data: dict[str, Any] = {
            "query": query,
            "action": action,
            "target_list_ids": target_list_ids,
        }
        if status is not None:
            data["status"] = status
        return await self._request("PUT", "/api/subscribers/query/lists", json_data=data)

    async def manage_subscriber_lists(
        self,
        action: str,
        target_list_ids: list[int],
        ids: list[int] | None = None,
        query: str | None = None,
        status: str | None = None,
        list_id: int | None = None,
    ) -> dict[str, Any]:
        """Add, remove, or unsubscribe subscribers from lists."""
        data: dict[str, Any] = {"action": action, "target_list_ids": target_list_ids}
        if ids is not None:
            data["ids"] = ids
        if query is not None:
            data["query"] = query
        if status is not None:
            data["status"] = status
        endpoint = f"/api/subscribers/lists/{list_id}" if list_id is not None else "/api/subscribers/lists"
        return await self._request("PUT", endpoint, json_data=data)

    async def get_bounces(
        self,
        campaign_id: int | None = None,
        page: int = 1,
        per_page: int | str = 20,
        source: str | None = None,
        order_by: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        """Get bounce records."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if campaign_id is not None:
            params["campaign_id"] = campaign_id
        if source is not None:
            params["source"] = source
        if order_by is not None:
            params["order_by"] = order_by
        if order is not None:
            params["order"] = order
        return await self._request("GET", "/api/bounces", params=params)

    async def get_bounce(self, bounce_id: int) -> dict[str, Any]:
        """Get a bounce record by ID."""
        return await self._request("GET", f"/api/bounces/{bounce_id}")

    async def delete_bounce(self, bounce_id: int) -> dict[str, Any]:
        """Delete a bounce record by ID."""
        return await self._request("DELETE", f"/api/bounces/{bounce_id}")

    async def delete_bounces(
        self,
        bounce_ids: list[int] | None = None,
        all: bool = False,
    ) -> dict[str, Any]:
        """Delete multiple bounce records."""
        params: dict[str, Any] = {"all": all}
        if bounce_ids is not None:
            params["id"] = bounce_ids
        return await self._request("DELETE", "/api/bounces", params=params)

    # List Operations
    async def get_lists(
        self,
        query: str | None = None,
        status: str | None = None,
        minimal: bool | None = None,
        tags: list[str] | None = None,
        order_by: str | None = None,
        order: str | None = None,
        page: int = 1,
        per_page: int | str = 20,
    ) -> dict[str, Any]:
        """Get all mailing lists."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if query is not None:
            params["query"] = query
        if status is not None:
            params["status"] = status
        if minimal is not None:
            params["minimal"] = minimal
        if tags is not None:
            params["tag"] = tags
        if order_by is not None:
            params["order_by"] = order_by
        if order is not None:
            params["order"] = order
        return await self._request("GET", "/api/lists", params=params)

    async def get_public_lists(self) -> dict[str, Any]:
        """Get public lists for subscription forms."""
        return await self._request("GET", "/api/public/lists")

    async def get_list(self, list_id: int) -> dict[str, Any]:
        """Get mailing list by ID."""
        return await self._request("GET", f"/api/lists/{list_id}")

    async def create_list(
        self,
        name: str,
        type: str = "public",
        optin: str = "single",
        tags: list[str] | None = None,
        description: str | None = None
    ) -> dict[str, Any]:
        """Create a new mailing list."""
        data = {
            "name": name,
            "type": type,
            "optin": optin,
            "tags": tags or [],
        }
        if description:
            data["description"] = description

        return await self._request("POST", "/api/lists", json_data=data)

    async def update_list(
        self,
        list_id: int,
        name: str | None = None,
        type: str | None = None,
        optin: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None
    ) -> dict[str, Any]:
        """Update an existing mailing list."""
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if type is not None:
            data["type"] = type
        if optin is not None:
            data["optin"] = optin
        if tags is not None:
            data["tags"] = tags
        if description is not None:
            data["description"] = description

        return await self._request("PUT", f"/api/lists/{list_id}", json_data=data)

    async def delete_list(self, list_id: int) -> dict[str, Any]:
        """Delete a mailing list."""
        return await self._request("DELETE", f"/api/lists/{list_id}")

    async def delete_lists(
        self,
        ids: list[int] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        """Delete multiple mailing lists by IDs or query."""
        params: dict[str, Any] = {}
        if ids is not None:
            params["id"] = ids
        if query is not None:
            params["query"] = query
        return await self._request("DELETE", "/api/lists", params=params)

    async def get_import_subscribers(self) -> dict[str, Any]:
        """Get subscriber import status."""
        return await self._request("GET", "/api/import/subscribers")

    async def get_import_subscriber_logs(self) -> dict[str, Any]:
        """Get subscriber import logs."""
        return await self._request("GET", "/api/import/subscribers/logs")

    async def stop_import_subscribers(self) -> dict[str, Any]:
        """Stop and remove a subscriber import."""
        return await self._request("DELETE", "/api/import/subscribers")

    async def import_subscribers(
        self,
        file_path: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Upload a file for bulk subscriber import."""
        from pathlib import Path

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise ListmonkAPIError(f"File not found: {file_path}")

        url = self._build_url("/api/import/subscribers")
        with open(file_path, "rb") as file_handle:
            files = {"file": (file_path_obj.name, file_handle.read(), "application/octet-stream")}
        data = {"params": json.dumps(params)}

        upload_client = AsyncClient(
            timeout=self.config.timeout,
            headers={
                "Authorization": f"token {self.config.username}:{self.config.password}",
                "User-Agent": "Listmonk-MCP-Server/0.1.0",
                "Accept": "application/json",
            }
        )
        try:
            response = await upload_client.post(url, files=files, data=data)
            return await self._handle_response(response)
        except httpx.RequestError as e:
            raise ListmonkAPIError(f"Subscriber import failed: {str(e)}") from e
        finally:
            await upload_client.aclose()

    async def get_list_subscribers(self, list_id: int, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        """Get subscribers for a specific list."""
        params = {"page": page, "per_page": per_page, "list_id": list_id}
        return await self._request("GET", "/api/subscribers", params=params)

    # Campaign Operations
    async def get_campaigns(
        self,
        page: int = 1,
        per_page: int | str = 20,
        status: str | list[str] | None = None,
        query: str | None = None,
        tags: list[str] | None = None,
        order_by: str | None = None,
        order: str | None = None,
        no_body: bool | None = None,
    ) -> dict[str, Any]:
        """Get campaigns with pagination and filtering."""
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if status is not None:
            params["status"] = status
        if query is not None:
            params["query"] = query
        if tags is not None:
            params["tags"] = tags
        if order_by is not None:
            params["order_by"] = order_by
        if order is not None:
            params["order"] = order
        if no_body is not None:
            params["no_body"] = no_body

        return await self._request("GET", "/api/campaigns", params=params)

    async def get_campaign(self, campaign_id: int, no_body: bool | None = None) -> dict[str, Any]:
        """Get campaign by ID."""
        params = {"no_body": no_body} if no_body is not None else None
        return await self._request("GET", f"/api/campaigns/{campaign_id}", params=params)

    async def create_campaign(
        self,
        name: str,
        subject: str,
        lists: list[int],
        type: str = "regular",
        content_type: str = "richtext",
        body: str | None = None,
        altbody: str | None = None,
        from_email: str | None = None,
        messenger: str | None = None,
        template_id: int | None = None,
        tags: list[str] | None = None,
        send_later: bool | None = None,
        send_at: str | None = None,
        headers: list[dict[str, Any]] | None = None,
        auto_convert_plain_to_html: bool = True
    ) -> dict[str, Any]:
        """Create a new campaign."""
        if body is not None:
            body, content_type = normalize_body(
                body,
                content_type,
                auto_convert_plain_to_html,
            )

        data: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "lists": lists,
            "type": type,
            "content_type": content_type,
            "tags": tags or []
        }

        if body:
            data["body"] = body
        if altbody is not None:
            data["altbody"] = altbody
        if from_email is not None:
            data["from_email"] = from_email
        if messenger is not None:
            data["messenger"] = messenger
        if template_id:
            data["template_id"] = template_id
        if send_later is not None:
            data["send_later"] = send_later
        if send_at is not None:
            data["send_at"] = send_at
        if headers is not None:
            data["headers"] = headers

        return await self._request("POST", "/api/campaigns", json_data=data)

    async def update_campaign(
        self,
        campaign_id: int,
        name: str | None = None,
        subject: str | None = None,
        lists: list[int] | None = None,
        body: str | None = None,
        altbody: str | None = None,
        from_email: str | None = None,
        content_type: str | None = None,
        messenger: str | None = None,
        type: str | None = None,
        tags: list[str] | None = None,
        template_id: int | None = None,
        send_later: bool | None = None,
        send_at: str | None = None,
        headers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update an existing campaign.

        If lists is not provided, fetches the current campaign's lists to preserve them.
        """
        # If lists not provided, fetch current campaign to get existing lists
        if lists is None:
            current = await self.get_campaign(campaign_id)
            campaign_data = current.get("data", {})
            current_lists = campaign_data.get("lists", [])
            lists = [lst.get("id") for lst in current_lists if lst.get("id")]

        data: dict[str, Any] = {"lists": lists}
        if name is not None:
            data["name"] = name
        if subject is not None:
            data["subject"] = subject
        if body is not None:
            data["body"] = body
        if altbody is not None:
            data["altbody"] = altbody
        if from_email is not None:
            data["from_email"] = from_email
        if content_type is not None:
            data["content_type"] = content_type
        if messenger is not None:
            data["messenger"] = messenger
        if type is not None:
            data["type"] = type
        if tags is not None:
            data["tags"] = tags
        if template_id is not None:
            data["template_id"] = template_id
        if send_later is not None:
            data["send_later"] = send_later
        if send_at is not None:
            data["send_at"] = send_at
        if headers is not None:
            data["headers"] = headers

        return await self._request("PUT", f"/api/campaigns/{campaign_id}", json_data=data)

    async def delete_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Delete a campaign."""
        return await self._request("DELETE", f"/api/campaigns/{campaign_id}")

    async def delete_campaigns(
        self,
        ids: list[int] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        """Delete multiple campaigns by IDs or query."""
        params: dict[str, Any] = {}
        if ids is not None:
            params["id"] = ids
        if query is not None:
            params["query"] = query
        return await self._request("DELETE", "/api/campaigns", params=params)

    async def send_campaign(self, campaign_id: int) -> dict[str, Any]:
        """Send a campaign immediately."""
        return await self.update_campaign_status(campaign_id, "running")

    async def schedule_campaign(self, campaign_id: int, send_at: str) -> dict[str, Any]:
        """Schedule a campaign for future delivery."""
        data = {"status": "scheduled", "send_at": send_at}
        return await self._request("PUT", f"/api/campaigns/{campaign_id}/status", json_data=data)

    async def update_campaign_status(self, campaign_id: int, status: str) -> dict[str, Any]:
        """Update a campaign status."""
        return await self._request("PUT", f"/api/campaigns/{campaign_id}/status", json_data={"status": status})

    async def get_campaign_preview(self, campaign_id: int) -> dict[str, Any]:
        """Get campaign HTML preview."""
        return await self._request("GET", f"/api/campaigns/{campaign_id}/preview")

    async def preview_campaign_body(
        self,
        campaign_id: int,
        body: str,
        content_type: str,
        template_id: int | None = None,
    ) -> dict[str, Any]:
        """Render a campaign HTML preview from body content."""
        data: dict[str, Any] = {"body": body, "content_type": content_type}
        if template_id is not None:
            data["template_id"] = template_id
        return await self._request_form("POST", f"/api/campaigns/{campaign_id}/preview", data=data)

    async def preview_campaign_text(
        self,
        campaign_id: int,
        body: str,
        content_type: str,
        template_id: int | None = None,
    ) -> dict[str, Any]:
        """Render a campaign text preview from body content."""
        data: dict[str, Any] = {"body": body, "content_type": content_type}
        if template_id is not None:
            data["template_id"] = template_id
        return await self._request_form("POST", f"/api/campaigns/{campaign_id}/text", data=data)

    async def get_running_campaign_stats(self, campaign_ids: list[int]) -> dict[str, Any]:
        """Get running stats for campaign IDs."""
        return await self._request("GET", "/api/campaigns/running/stats", params={"campaign_id": campaign_ids})

    async def get_campaign_analytics(
        self,
        type: str,
        campaign_ids: list[int],
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        """Get campaign analytics counts."""
        params = {
            "id": ",".join(str(campaign_id) for campaign_id in campaign_ids),
            "from": from_date,
            "to": to_date,
        }
        return await self._request("GET", f"/api/campaigns/analytics/{type}", params=params)

    async def archive_campaign(
        self,
        campaign_id: int,
        archive: bool = True,
        archive_template_id: int | None = None,
        archive_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish or unpublish a campaign in the public archive."""
        data: dict[str, Any] = {"archive": archive}
        if archive_template_id is not None:
            data["archive_template_id"] = archive_template_id
        if archive_meta is not None:
            data["archive_meta"] = archive_meta
        return await self._request("PUT", f"/api/campaigns/{campaign_id}/archive", json_data=data)

    async def convert_campaign_content(
        self,
        campaign_id: int,
        body: str,
        content_type: str,
        template_id: int | None = None,
    ) -> dict[str, Any]:
        """Convert campaign body content with Listmonk's content endpoint."""
        data: dict[str, Any] = {"body": body, "content_type": content_type}
        if template_id is not None:
            data["template_id"] = template_id
        return await self._request("POST", f"/api/campaigns/{campaign_id}/content", json_data=data)

    async def test_campaign(
        self,
        campaign_id: int,
        subscribers: list[str],
        template_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a campaign test to arbitrary subscriber emails."""
        data: dict[str, Any] = {"subscribers": subscribers}
        if template_id is not None:
            data["template_id"] = template_id
        return await self._request("POST", f"/api/campaigns/{campaign_id}/test", json_data=data)

    # Template Operations
    async def get_templates(self, no_body: bool | None = None) -> dict[str, Any]:
        """Get all email templates."""
        params = {"no_body": no_body} if no_body is not None else None
        return await self._request("GET", "/api/templates", params=params)

    async def get_template(self, template_id: int, no_body: bool | None = None) -> dict[str, Any]:
        """Get template by ID."""
        params = {"no_body": no_body} if no_body is not None else None
        return await self._request("GET", f"/api/templates/{template_id}", params=params)

    async def create_template(
        self,
        name: str,
        subject: str,
        body: str,
        type: str = "campaign",
        is_default: bool = False,
        body_source: str | None = None,
    ) -> dict[str, Any]:
        """Create a new email template."""
        data = {
            "name": name,
            "subject": subject,
            "body": body,
            "type": type,
            "is_default": is_default
        }
        if body_source is not None:
            data["body_source"] = body_source
        return await self._request("POST", "/api/templates", json_data=data)

    async def update_template(
        self,
        template_id: int,
        name: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        is_default: bool | None = None,
        type: str | None = None,
        body_source: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing template.

        Fetches the current template first and merges changes, as Listmonk
        requires all fields in PUT requests.
        """
        # Fetch current template to get all existing values
        current = await self.get_template(template_id)
        template_data = current.get("data", {})

        # Build update data with current values as defaults
        # IMPORTANT: type must be included, otherwise Listmonk validates as transactional template
        data: dict[str, Any] = {
            "name": name if name is not None else template_data.get("name", ""),
            "subject": subject if subject is not None else template_data.get("subject", ""),
            "type": type if type is not None else template_data.get("type", "campaign"),
            "body": body if body is not None else template_data.get("body", ""),
            "is_default": is_default if is_default is not None else template_data.get("is_default", False),
        }
        current_body_source = template_data.get("body_source")
        if body_source is not None:
            data["body_source"] = body_source
        elif current_body_source is not None:
            data["body_source"] = current_body_source

        return await self._request("PUT", f"/api/templates/{template_id}", json_data=data)

    async def delete_template(self, template_id: int) -> dict[str, Any]:
        """Delete a template."""
        return await self._request("DELETE", f"/api/templates/{template_id}")

    async def preview_template(
        self,
        body: str,
        template_type: str = "campaign",
    ) -> dict[str, Any]:
        """Preview a template body."""
        return await self._request_form("POST", "/api/templates/preview", data={"body": body, "template_type": template_type})

    async def get_template_preview(
        self,
        template_id: int,
        body: str | None = None,
        template_type: str = "campaign",
    ) -> dict[str, Any]:
        """Get a template preview by ID."""
        if body is None:
            return await self._request("GET", f"/api/templates/{template_id}/preview")
        return await self._request_form(
            "POST",
            f"/api/templates/{template_id}/preview",
            data={"body": body, "template_type": template_type},
        )

    async def set_default_template(self, template_id: int) -> dict[str, Any]:
        """Set a template as the default template."""
        return await self._request("PUT", f"/api/templates/{template_id}/default")

    # Transactional Email
    async def send_transactional_email(
        self,
        template_id: int,
        subscriber_email: str | None = None,
        subscriber_id: int | None = None,
        subscriber_emails: list[str] | None = None,
        subscriber_ids: list[int] | None = None,
        subscriber_mode: str | None = None,
        from_email: str | None = None,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
        headers: list[dict[str, Any]] | None = None,
        messenger: str | None = None,
        content_type: str = "html",
        altbody: str | None = None,
    ) -> dict[str, Any]:
        """Send a transactional email."""
        payload: dict[str, Any] = {"template_id": template_id, "data": data or {}, "content_type": content_type}
        if subscriber_email is not None:
            payload["subscriber_email"] = subscriber_email
        if subscriber_id is not None:
            payload["subscriber_id"] = subscriber_id
        if subscriber_emails is not None:
            payload["subscriber_emails"] = subscriber_emails
        if subscriber_ids is not None:
            payload["subscriber_ids"] = subscriber_ids
        if subscriber_mode is not None:
            payload["subscriber_mode"] = subscriber_mode
        if from_email is not None:
            payload["from_email"] = from_email
        if subject is not None:
            payload["subject"] = subject
        if headers is not None:
            payload["headers"] = headers
        if messenger is not None:
            payload["messenger"] = messenger
        if altbody is not None:
            payload["altbody"] = altbody
        return await self._request("POST", "/api/tx", json_data=payload)

    # Media Operations
    async def get_media(self) -> dict[str, Any]:
        """Get all media files."""
        return await self._request("GET", "/api/media")

    async def get_media_file(self, media_id: int) -> dict[str, Any]:
        """Get a media file by ID."""
        return await self._request("GET", f"/api/media/{media_id}")

    async def create_public_subscription(
        self,
        name: str,
        email: str,
        list_uuids: list[str],
    ) -> dict[str, Any]:
        """Create a public subscription."""
        return await self._request(
            "POST",
            "/api/public/subscription",
            json_data={"name": name, "email": email, "list_uuids": list_uuids},
        )

    async def delete_gc_subscribers(self, type: str) -> dict[str, Any]:
        """Delete orphaned or blocklisted subscribers."""
        return await self._request("DELETE", f"/api/maintenance/subscribers/{type}")

    async def delete_campaign_analytics(self, type: str, before_date: str) -> dict[str, Any]:
        """Delete campaign analytics before a date."""
        return await self._request_form(
            "DELETE",
            f"/api/maintenance/analytics/{type}",
            data={"before_date": before_date},
        )

    async def delete_unconfirmed_subscriptions(self, before_date: str) -> dict[str, Any]:
        """Delete unconfirmed subscriptions before a date."""
        return await self._request_form(
            "DELETE",
            "/api/maintenance/subscriptions/unconfirmed",
            data={"before_date": before_date},
        )

    async def upload_media(self, file_path: str, title: str | None = None) -> dict[str, Any]:
        """Upload a media file.

        Args:
            file_path: Absolute path to the file to upload
            title: Optional title for the media file (defaults to filename)

        Returns:
            Dict containing the uploaded media data including URL
        """
        from pathlib import Path

        url = self._build_url("/api/media")

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise ListmonkAPIError(f"File not found: {file_path}")

        # Determine content type from file extension
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.svg': 'image/svg+xml',
        }
        ext = file_path_obj.suffix.lower()
        content_type = content_types.get(ext, 'application/octet-stream')

        # Use filename as title if not provided
        if title is None:
            title = file_path_obj.name

        # Read file content
        with open(file_path, 'rb') as f:
            file_content = f.read()

        # Prepare multipart form data
        files = {
            'file': (file_path_obj.name, file_content, content_type)
        }
        data = {}
        if title:
            data['title'] = title

        # Create a new client without Content-Type header for multipart upload
        # The client will automatically set multipart/form-data with boundary
        upload_client = AsyncClient(
            timeout=self.config.timeout,
            headers={
                "Authorization": f"token {self.config.username}:{self.config.password}",
                "User-Agent": "Listmonk-MCP-Server/0.1.0",
                "Accept": "application/json",
                # No Content-Type - will be set automatically by httpx for multipart
            }
        )

        try:
            response = await upload_client.post(url, files=files, data=data)
            return await self._handle_response(response)
        except httpx.RequestError as e:
            raise ListmonkAPIError(f"Media upload failed: {str(e)}") from e
        finally:
            await upload_client.aclose()

    async def update_media(self, media_id: int, title: str) -> dict[str, Any]:
        """Update media file metadata (rename).

        Args:
            media_id: ID of the media file
            title: New title for the media file
        """
        data = {"title": title}
        return await self._request("PUT", f"/api/media/{media_id}", json_data=data)

    async def delete_media(self, media_id: int) -> dict[str, Any]:
        """Delete a media file.

        Args:
            media_id: ID of the media file to delete
        """
        return await self._request("DELETE", f"/api/media/{media_id}")


async def create_client(config: Config) -> ListmonkClient:
    """Create and connect a Listmonk client."""
    client = ListmonkClient(config)
    await client.connect()
    return client
