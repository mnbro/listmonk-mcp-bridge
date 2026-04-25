# VS Code Setup

Add the Listmonk MCP server to your VS Code settings.

## Configuration

Add to your `~/.config/Code/User/settings.json`:

```json
{
  "mcp": {
    "servers": {
      "listmonk": {
        "command": "uvx",
        "args": ["listmonk-mcp-bridge"],
        "env": {
          "LISTMONK_MCP_URL": "http://localhost:9000",
          "LISTMONK_MCP_USERNAME": "your-api-username",
          "LISTMONK_MCP_PASSWORD": "your-api-token"
        }
      }
    }
  }
}
```

## Environment Variables

- `LISTMONK_MCP_URL`: Your Listmonk server URL
- `LISTMONK_MCP_USERNAME`: API user created in Admin → Users
- `LISTMONK_MCP_PASSWORD`: API token (not user password)

## Prerequisites

1. **Install uvx** (if not already installed):
   ```bash
   pip install uv
   ```

2. **Create API user and token** in Listmonk admin interface:
   - Go to Admin → Users in your Listmonk instance
   - Create a new API user and token

3. **Restart VS Code** after adding configuration