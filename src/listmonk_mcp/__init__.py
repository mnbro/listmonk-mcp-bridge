"""Listmonk MCP Server package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("listmonk-mcp-bridge")
except PackageNotFoundError:
    __version__ = "0+unknown"

# Core components
from .client import ListmonkAPIError, ListmonkClient
from .config import Config, get_config

# Essential models
from .models import (
    Campaign,
    MailingList,
    Subscriber,
    Template,
    TransactionalEmailModel,
)
from .server import mcp

__all__ = [
    "ListmonkClient",
    "ListmonkAPIError",
    "Config",
    "Subscriber",
    "MailingList",
    "Campaign",
    "Template",
    "TransactionalEmailModel",
    "get_config",
    "mcp",
]
