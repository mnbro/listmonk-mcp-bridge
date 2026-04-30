# Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv run python -m mypy src tests
uv run mkdocs build --strict
uv build
```

## Docker Build

```bash
docker build -t listmonk-mcp-bridge:local .
```

## Staging Smoke Tests

Staging smoke tests are opt-in and should only run against a disposable or staging Listmonk instance. They exercise settings update, import and email send paths.

## Documentation

Documentation is versioned in `docs/` and published to GitHub Pages through the docs workflow.

## Acknowledgements

Earlier project history referenced `rhnvrm/listmonk-mcp`. The current implementation was rewritten around the public Listmonk API surface and this project's own safety and operational requirements.
