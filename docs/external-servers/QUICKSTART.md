# Quick Start: External MCP Servers

Get external MCP servers running in 5 minutes.

## Prerequisites

- ToolDock installed and running
- Node.js (for npm-based servers) or Python with `uvx` (for PyPI servers)

## Step 1: Choose a Server

Browse the [MCP Registry](https://registry.modelcontextprotocol.io) or search via API:

```bash
curl "http://localhost:8006/admin/servers/search?query=filesystem" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Step 2: Configure the Server

Edit `tools/external/config.yaml`:

```yaml
servers:
  # Example: Filesystem server
  filesystem:
    source: registry
    name: "io.github.Digital-Defiance/mcp-filesystem"
    enabled: true

  # Example: Custom command
  my-server:
    source: custom
    enabled: true
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/home/user/documents"
```

## Step 3: Restart ToolDock

```bash
# Docker
docker compose restart

# Manual
SERVER_MODE=both python main.py
```

## Step 4: Verify

Check the tools are loaded:

```bash
# Via health endpoint
curl http://localhost:8006/health

# Via tools list
curl http://localhost:8006/tools \
  -H "Authorization: Bearer YOUR_TOKEN"
```

You should see tools like `filesystem:read_file`, `filesystem:write_file`, etc.

## Step 5: Use the Tools

OpenAPI:
```bash
curl -X POST "http://localhost:8006/tools/filesystem:read_file" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"path": "/home/user/documents/readme.txt"}'
```

MCP:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "filesystem:read_file",
    "arguments": {"path": "/home/user/documents/readme.txt"}
  }
}
```

## Alternative: Add via Admin API

No config file editing needed:

```bash
curl -X POST "http://localhost:8006/admin/servers/add" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "filesystem",
    "source": "registry",
    "name": "io.github.Digital-Defiance/mcp-filesystem"
  }'
```

## Popular Servers

| Server | Tools | Description |
|--------|-------|-------------|
| `modelcontextprotocol/server-filesystem` | 5 | File operations |
| `modelcontextprotocol/server-github` | 12 | GitHub API |
| `modelcontextprotocol/server-postgres` | 4 | PostgreSQL queries |
| `modelcontextprotocol/server-slack` | 8 | Slack integration |

## Troubleshooting

### Server won't start
- Check if the required runtime (node/python) is installed
- Check environment variables are set
- View logs: `docker compose logs -f`

### Tools not appearing
- Verify `enabled: true` in config
- Check server was loaded: `curl http://localhost:8006/admin/servers/installed`

### Tool execution fails
- Ensure required env vars are set (like `GITHUB_TOKEN`)
- Check server-specific documentation

## Next Steps

- [Configuration Reference](./CONFIGURATION.md) - All config options
- [Registry Guide](./REGISTRY.md) - Browse and discover servers
