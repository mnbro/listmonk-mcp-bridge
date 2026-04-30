# MCP Clients

Most MCP clients can start this server as a local command:

```json
{
  "mcpServers": {
    "listmonk-mcp-bridge": {
      "command": "uvx",
      "args": ["listmonk-mcp-bridge"],
      "env": {
        "LISTMONK_MCP_URL": "https://listmonk.example.com",
        "LISTMONK_MCP_USERNAME": "api-user",
        "LISTMONK_MCP_PASSWORD": "your-api-token"
      }
    }
  }
}
```

If installed globally:

```json
{
  "mcpServers": {
    "listmonk-mcp-bridge": {
      "command": "listmonk-mcp-bridge",
      "env": {
        "LISTMONK_MCP_URL": "https://listmonk.example.com",
        "LISTMONK_MCP_USERNAME": "api-user",
        "LISTMONK_MCP_PASSWORD": "your-api-token"
      }
    }
  }
}
```

Docker-based clients can use the config in [Docker](docker.md).

Client-specific pages:

- [Claude Desktop](claude-desktop.md)
- [VS Code](vscode.md)
- [Cline](cline.md)
- [Windsurf & Cursor](windsurf-cursor.md)
