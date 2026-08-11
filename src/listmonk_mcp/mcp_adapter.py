"""Narrow integration boundary for the public MCP Python SDK API."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, TypeAlias, TypeVar

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

MCPServerType: TypeAlias = MCPServer[Any]
MCPHandler = TypeVar("MCPHandler", bound=Callable[..., Any])
MCPLifespan: TypeAlias = Callable[[MCPServerType], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True, slots=True)
class ToolHints:
    """SDK-independent tool risk hints used by the bridge policy layer."""

    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool = True

    def to_mcp(self) -> ToolAnnotations:
        """Translate bridge policy hints to the MCP v2 public wire model."""

        return ToolAnnotations(
            read_only_hint=self.read_only,
            destructive_hint=self.destructive,
            idempotent_hint=self.idempotent,
            open_world_hint=self.open_world,
        )


class MCPRuntime:
    """Own MCP server construction, registration, and transport startup."""

    def __init__(self, *, name: str, lifespan: MCPLifespan) -> None:
        self.server: MCPServerType = MCPServer(name=name, lifespan=lifespan)

    def tool(self, *, annotations: ToolHints) -> Callable[[MCPHandler], MCPHandler]:
        return self.server.tool(annotations=annotations.to_mcp())

    def resource(self, uri: str) -> Callable[[MCPHandler], MCPHandler]:
        return self.server.resource(uri)

    def prompt(self) -> Callable[[MCPHandler], MCPHandler]:
        return self.server.prompt()

    def run_stdio(self) -> None:
        """Run the supported production transport."""

        self.server.run(transport="stdio")
