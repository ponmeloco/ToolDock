# MCP Registry Guide

How to discover and use servers from the official MCP Registry.

## What is the MCP Registry?

The [MCP Registry](https://registry.modelcontextprotocol.io) is a central directory of MCP servers published by the community. It contains hundreds of servers for various services:

- GitHub, GitLab, Bitbucket
- Slack, Discord, Teams
- PostgreSQL, MySQL, MongoDB
- File systems, cloud storage
- And many more...

## Browsing the Registry

### Via Web

Visit https://registry.modelcontextprotocol.io to browse servers with descriptions and documentation.

### Via Admin API

Search from ToolDock:

```bash
curl "http://localhost:18006/admin/servers/search?query=github" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Response:
```json
[
  {
    "name": "modelcontextprotocol/server-github",
    "description": "GitHub API integration with repository, issue, and PR management",
    "version": "1.0.0",
    "type": "stdio",
    "package_or_url": "@modelcontextprotocol/server-github"
  }
]
```

### Via Direct API

```bash
curl "https://registry.modelcontextprotocol.io/v0/servers?search=github"
```

## Server Types

### Package Servers (STDIO)

Most registry servers are distributed as packages:

| Type | Command | Example |
|------|---------|---------|
| npm | `npx -y <package>` | `npx -y @modelcontextprotocol/server-github` |
| PyPI | `uvx <package>` | `uvx mcp-server-postgres` |
| OCI | `docker run <image>` | `docker run -i mcp/server` |

### Remote Servers (HTTP)

Some servers are hosted remotely:

```json
{
  "remotes": [{
    "type": "streamable-http",
    "url": "https://mcp.example.com/mcp"
  }]
}
```

## Using Registry Servers

### Method 1: Config File

```yaml
# tooldock_data/external/config.yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
```

### Method 2: Admin API

```bash
curl -X POST "http://localhost:18006/admin/servers/add" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "github",
    "source": "registry",
    "name": "modelcontextprotocol/server-github",
    "env": {"GITHUB_TOKEN": "ghp_xxx"}
  }'
```

## Server Naming

Registry server names follow the pattern:
```
<namespace>/<server-name>
```

Examples:
- `modelcontextprotocol/server-github`
- `io.github.Digital-Defiance/mcp-filesystem`
- `ai.anthropic/claude-mcp-server`

## Environment Variables

Most servers require configuration via environment variables. Check the registry page for required variables.

Common patterns:
- `<SERVICE>_TOKEN` - API tokens
- `<SERVICE>_API_KEY` - API keys
- `DATABASE_URL` - Connection strings
- `<SERVICE>_ORG` - Organization/workspace names

## Popular Servers

| Server | Package | Required Env |
|--------|---------|--------------|
| GitHub | `@modelcontextprotocol/server-github` | `GITHUB_TOKEN` |
| Filesystem | `@modelcontextprotocol/server-filesystem` | (paths as args) |
| PostgreSQL | `mcp-server-postgres` | `POSTGRES_CONNECTION_STRING` |
| Slack | `@modelcontextprotocol/server-slack` | `SLACK_BOT_TOKEN` |

## Troubleshooting

### "Server not found in registry"

- Check the exact server name (case-sensitive)
- The server might have been removed or renamed
- Try searching to find the correct name

### "Command not found"

For npm packages:
```bash
npm install -g npx
```

For PyPI packages:
```bash
pip install uvx
```

### "Environment variable not set"

Ensure all required environment variables are defined:
```bash
export GITHUB_TOKEN=ghp_xxxx
```

Or in `docker-compose.yml`:
```yaml
environment:
  - GITHUB_TOKEN=${GITHUB_TOKEN}
```
