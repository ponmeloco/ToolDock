# Admin API Reference

Runtime management of external MCP servers.

**Base URL:** `http://localhost:8006/admin`

**Authentication:** Bearer token required (same as other endpoints)

## Endpoints

### Search Registry

Search the MCP Registry for available servers.

```
GET /admin/servers/search?query={query}&limit={limit}
```

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| query | string | required | Search query |
| limit | int | 20 | Max results (1-100) |

**Response:**
```json
[
  {
    "name": "modelcontextprotocol/server-github",
    "description": "GitHub API integration",
    "version": "1.0.0",
    "type": "stdio",
    "package_or_url": "@modelcontextprotocol/server-github"
  }
]
```

**Example:**
```bash
curl "http://localhost:8006/admin/servers/search?query=github" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### List Installed Servers

Get all currently connected external servers.

```
GET /admin/servers/installed
```

**Response:**
```json
[
  {
    "server_id": "github",
    "status": "connected",
    "tools": 12,
    "tool_names": ["create_repository", "list_repos", ...],
    "config_type": "stdio"
  }
]
```

**Example:**
```bash
curl "http://localhost:8006/admin/servers/installed" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### Add Server

Connect to a new external MCP server.

```
POST /admin/servers/add
```

**Request Body:**
```json
{
  "server_id": "string (required)",
  "source": "registry | custom",
  "name": "string (for registry source)",
  "command": "string (for custom stdio)",
  "args": ["array", "of", "args"],
  "env": {"KEY": "value"},
  "url": "string (for custom http)",
  "save_to_config": true
}
```

**Response:**
```json
{
  "server_id": "github",
  "status": "connected",
  "tools": 12,
  "tool_names": ["github:create_repository", ...]
}
```

**Examples:**

From registry:
```bash
curl -X POST "http://localhost:8006/admin/servers/add" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "github",
    "source": "registry",
    "name": "modelcontextprotocol/server-github",
    "env": {"GITHUB_TOKEN": "ghp_xxx"}
  }'
```

Custom command:
```bash
curl -X POST "http://localhost:8006/admin/servers/add" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "my-server",
    "source": "custom",
    "command": "python",
    "args": ["/path/to/server.py"]
  }'
```

---

### Remove Server

Disconnect and remove an external server.

```
DELETE /admin/servers/{server_id}?remove_from_config={bool}
```

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| server_id | string | required | Server identifier |
| remove_from_config | bool | true | Also remove from config.yaml |

**Response:**
```json
{
  "status": "removed",
  "server_id": "github"
}
```

**Example:**
```bash
curl -X DELETE "http://localhost:8006/admin/servers/github" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### List All Tools

Get all tools with type breakdown.

```
GET /admin/tools
```

**Response:**
```json
{
  "native": {
    "count": 5,
    "tools": [
      {"name": "example_tool", "description": "..."}
    ]
  },
  "external": {
    "count": 12,
    "tools": [
      {"name": "github:create_repository", "description": "...", "server": "github"}
    ]
  },
  "total": 17
}
```

**Example:**
```bash
curl "http://localhost:8006/admin/tools" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### Get Stats

Get server and tool statistics.

```
GET /admin/stats
```

**Response:**
```json
{
  "tools": {
    "native": 5,
    "external": 12,
    "total": 17
  },
  "servers": {
    "total_servers": 2,
    "connected_servers": 2,
    "total_tools": 12
  }
}
```

**Example:**
```bash
curl "http://localhost:8006/admin/stats" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Error Responses

### 400 Bad Request

Invalid request parameters:
```json
{
  "detail": "'name' is required for registry source"
}
```

### 401 Unauthorized

Missing or invalid token:
```json
{
  "detail": "Invalid token"
}
```

### 404 Not Found

Server or resource not found:
```json
{
  "detail": "Server not found: github"
}
```

### 502 Bad Gateway

Registry API error:
```json
{
  "detail": "Registry search failed: Connection timeout"
}
```

### 503 Service Unavailable

External server manager not ready:
```json
{
  "detail": "External server manager not initialized"
}
```
