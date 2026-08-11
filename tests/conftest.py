"""Make the shared in-process server configuration deterministic for tests."""

import os

os.environ.setdefault("LISTMONK_MCP_MODE", "full")
os.environ.setdefault("LISTMONK_MCP_READ_ONLY", "false")
os.environ.setdefault("LISTMONK_MCP_AUDIT_ENABLED", "false")
