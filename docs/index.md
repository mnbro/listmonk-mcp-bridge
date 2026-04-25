# Listmonk MCP Server

An MCP (Model Context Protocol) server for Listmonk, providing programmatic access to newsletter management through AI assistants and IDEs.

## Features

- Complete Listmonk API integration with async operations
- Subscriber management (CRUD with query/pagination support)
- List management with tags support
- Campaign creation, management, and sending
- Template management for campaigns and transactional messages
- Transactional email sending with template data
- Type-safe operations with Pydantic models

## Installation

### Using uvx (Recommended)

Install and run directly from PyPI:

```bash
# Run directly (installs if needed)
uvx listmonk-mcp-bridge --help

# Or install globally
uvx install listmonk-mcp-bridge
listmonk-mcp-bridge --help
```

### Using pip

```bash
pip install listmonk-mcp-bridge
```

## Quick Start

1. **Install the server using uvx:**
   ```bash
   uvx install listmonk-mcp-bridge
   ```

2. **Create API credentials in Listmonk:**
   - Go to Listmonk Admin → Users
   - Create a new API user and token

3. **Choose your setup:**
   - [Claude Desktop](./claude-desktop.md) - Claude Desktop app configuration
   - [VS Code](./vscode.md) - VS Code MCP settings  
   - [Cline](./cline.md) - Cline extension configuration
   - [Windsurf & Cursor](./windsurf-cursor.md) - Windsurf and Cursor IDE setup

## Configuration

All setups use the same basic configuration format:

```json
{
  "command": "uv",
  "args": ["run", "python", "-m", "listmonk_mcp.server"],
  "cwd": "/path/to/listmonk-mcp-bridge",
  "env": {
    "LISTMONK_MCP_URL": "http://localhost:9000",
    "LISTMONK_MCP_USERNAME": "your-api-username", 
    "LISTMONK_MCP_PASSWORD": "your-api-token"
  }
}
```

## API Coverage

The MCP server exposes 81 tools covering all 72 Listmonk Swagger operations plus focused convenience workflows:

- **Subscribers**: Get, create, update, delete with advanced filtering
- **Lists**: Full CRUD operations with tag support
- **Campaigns**: Create, manage, and send campaigns
- **Templates**: Access campaign and transactional templates
- **Transactional Messages**: Send individual emails with template data
- **Extended API Coverage**: Public lists, subscriber opt-in/export/bounces/list membership, bounces, import status/logs/stop, campaign stats/analytics/archive/test/content conversion, template preview/default, media lookup, and multi-recipient transactional messages

## Tool Behavior Notes

- `update_subscriber` supports partial updates and omits fields that were not provided.
- `create_template` supports campaign, `campaign_visual`, and transactional (`tx`) templates, including `subject` and `body_source`.
- `create_campaign` converts plain text bodies to escaped HTML by default when `content_type="plain"`. Set `auto_convert_plain_to_html=false` to preserve plain text unchanged.

## What is MCP?

The Model Context Protocol (MCP) is an open standard that enables AI assistants to securely connect to external data sources and tools. This server implements MCP to provide AI assistants with direct access to Listmonk's newsletter management capabilities.

## Requirements

- Python 3.11+
- Running Listmonk instance
- API credentials from Listmonk admin panel

---

📚 **Documentation built with MkDocs Material**
