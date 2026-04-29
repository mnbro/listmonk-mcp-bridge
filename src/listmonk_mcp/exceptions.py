"""Structured MCP error helpers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .client import ListmonkAPIError

logger = logging.getLogger(__name__)
T = TypeVar("T")


class ListmonkMCPError(Exception):
    """Base error carrying an MCP-safe response payload."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "error_type": type(self).__name__,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


class ValidationError(ListmonkMCPError):
    pass


class AuthenticationError(ListmonkMCPError):
    pass


class APIError(ListmonkMCPError):
    pass


class ConfigurationError(ListmonkMCPError):
    pass


class OperationError(ListmonkMCPError):
    def __init__(
        self,
        message: str,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.operation = operation

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.operation:
            result["operation"] = self.operation
        return result


class ResourceNotFoundError(OperationError):
    pass


class DuplicateResourceError(OperationError):
    pass


def convert_listmonk_api_error(error: ListmonkAPIError) -> ListmonkMCPError:
    """Map Listmonk HTTP failures to stable MCP error types."""

    details = error.response or {}
    status_code = error.status_code
    if status_code in {401, 403}:
        return AuthenticationError(str(error), details)
    if status_code == 404:
        return ResourceNotFoundError("Resource not found", details=details)
    if status_code == 409:
        return DuplicateResourceError("Resource already exists", details=details)
    if status_code is not None and 400 <= status_code < 500:
        return ValidationError(str(error), details)
    return APIError(str(error), details)


def format_mcp_error(error: ListmonkMCPError) -> dict[str, Any]:
    return {"success": False, "error": error.to_dict()}


def safe_execute(func: Callable[..., T], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return {"success": True, "data": func(*args, **kwargs)}
    except ListmonkMCPError as exc:
        return format_mcp_error(exc)
    except ListmonkAPIError as exc:
        return format_mcp_error(convert_listmonk_api_error(exc))
    except Exception as exc:
        logger.exception("Unexpected error while executing MCP helper")
        return format_mcp_error(
            OperationError(
                "Unexpected error while executing MCP tool", details={"error": str(exc)}
            )
        )


async def safe_execute_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return await func(*args, **kwargs)
    except ListmonkAPIError as exc:
        return format_mcp_error(convert_listmonk_api_error(exc))
    except Exception as exc:
        logger.exception("Unexpected error while executing MCP tool")
        return format_mcp_error(
            OperationError(
                "Unexpected error while executing MCP tool",
                operation=getattr(func, "__name__", None),
                details={"error": str(exc)},
            )
        )
