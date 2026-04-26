import os
from pathlib import Path
from uuid import uuid4

import pytest

from listmonk_mcp.client import ListmonkClient
from listmonk_mcp.config import Config

pytestmark = pytest.mark.skipif(
    os.getenv("LISTMONK_MCP_RUN_STAGING_SMOKE") != "true",
    reason="staging smoke tests require LISTMONK_MCP_RUN_STAGING_SMOKE=true",
)


def staging_config() -> Config:
    return Config(
        url=os.environ["LISTMONK_MCP_URL"],
        username=os.environ["LISTMONK_MCP_USERNAME"],
        password=os.environ["LISTMONK_MCP_PASSWORD"],
    )


@pytest.mark.asyncio
async def test_staging_update_settings_import_and_send_email_smoke(tmp_path: Path) -> None:
    list_id = int(os.environ["LISTMONK_MCP_SMOKE_LIST_ID"])
    campaign_id = int(os.environ["LISTMONK_MCP_SMOKE_CAMPAIGN_ID"])
    recipient = os.environ["LISTMONK_MCP_SMOKE_EMAIL"]

    client = ListmonkClient(staging_config())
    try:
        settings_response = await client.get_settings()
        settings = settings_response.get("data", settings_response)
        assert isinstance(settings, dict)
        await client.update_settings(settings)

        import_file = tmp_path / "subscribers.csv"
        import_file.write_text(
            f"email,name\nsmoke-{uuid4().hex}@example.com,Smoke Test\n",
            encoding="utf-8",
        )
        await client.import_subscribers(
            file_path=str(import_file),
            params={
                "mode": "subscribe",
                "delim": ",",
                "lists": [list_id],
                "overwrite": False,
            },
        )

        await client.test_campaign(campaign_id=campaign_id, subscribers=[recipient])
    finally:
        await client.close()
