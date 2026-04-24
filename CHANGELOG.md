# Changelog

## 0.2.0

- Return structured dictionaries from MCP tools instead of human-only summary strings.
- Register tools directly on the production FastMCP server instead of copying private internals.
- Return structured error responses without exposing tracebacks to MCP clients.
- Add CI for linting, tests, type checking, and package builds on Python 3.11 and 3.12.
- Add regression tests for structured responses and error handling.
- Replace deprecated Pydantic `min_items` usage with `min_length`.

## 0.1.1

- Harden MCP error handling and release validation.
- Add package metadata for PyPI.

## 0.1.0

- Initial public package release.
