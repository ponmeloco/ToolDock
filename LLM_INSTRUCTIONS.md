# LLM Instructions for ToolDock

## Role of the Model

The language model acts as an orchestrator that decides when to call tools. ToolDock exposes tools via multiple transports - use whichever is configured for your environment.

## Rules

- Only use parameters defined in the tool schema
- Never invent parameters
- Prefer tools over guessing
- Treat tool responses as authoritative
- Do not hallucinate tool capabilities

## Authentication

All API endpoints (except health checks) require Bearer token authentication,
including requests from `localhost`:

```
Authorization: Bearer <token>
```

## Tool Discovery

Tools are organized in **namespaces** (folders). Each namespace has its own endpoint.

## Default Ports (Docker Compose)

In the default `docker compose` setup, only the gateway is exposed on the host:

- Gateway (Admin UI + `/api` + `/openapi` + `/mcp`): `http://localhost:13000`
- Backend internal-only ports (Docker network): `8006` (OpenAPI), `8007` (MCP), `8080` (Backend API)

### OpenAPI Transport (Port 8006)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/tools` | GET | List all tools from all namespaces |
| `/tools/{tool_name}` | POST | Execute a tool |

**Example - List Tools:**
```bash
curl http://localhost:13000/openapi/tools \
  -H "Authorization: Bearer <token>"
```

**Example - Execute Tool:**
```bash
curl -X POST http://localhost:13000/openapi/tools/hello_world \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "World"}'
```

### MCP Streamable HTTP Transport (Port 8007)

Uses JSON-RPC 2.0 protocol with namespace-based routing.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth) |
| `/mcp/namespaces` | GET | List all namespaces |
| `/mcp` | GET | SSE stream (requires `Accept: text/event-stream`) |
| `/mcp` | POST | Global endpoint (all tools) |
| `/mcp/{namespace}` | GET | SSE stream (requires `Accept: text/event-stream`) |
| `/mcp/{namespace}` | POST | Namespace-specific endpoint |

**Example - List Namespaces:**
```bash
curl http://localhost:13000/mcp/namespaces \
  -H "Authorization: Bearer <token>"
```

**Example - SSE Stream (kept alive):**
```bash
curl http://localhost:13000/mcp \
  -H "Authorization: Bearer <token>" \
  -H "Accept: text/event-stream"
```

**Example - List Tools (shared namespace):**
```bash
curl -X POST http://localhost:13000/mcp/shared \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

**Example - Execute Tool:**
```bash
curl -X POST http://localhost:13000/mcp/shared \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "hello_world",
      "arguments": {"name": "World"}
    }
  }'
```

## Namespace Routing

Tools are organized in namespaces (folders):

| Folder | MCP Endpoint | Description |
|--------|--------------|-------------|
| `tools/shared/` | `/mcp/shared` | Default shared tools |
| `tools/team1/` | `/mcp/team1` | Team-specific tools |
| `tools/finance/` | `/mcp/finance` | Department tools |

When connecting via MCP, you can either:
- Use `/mcp` to access ALL tools from all namespaces
- Use `/mcp/{namespace}` to access only tools from that namespace

## Tool Execution

Both transports use the same underlying tools. A tool call requires:

1. **Tool name** - Exact name as listed (case-sensitive)
2. **Arguments** - JSON object matching the input schema exactly

## Error Handling

- Invalid parameters return validation errors with details
- Unknown tools return "tool not found"
- Execution errors are returned as structured error objects
- Authentication failures return 401 Unauthorized

## MCP JSON-RPC Methods

| Method | Description |
|--------|-------------|
| `initialize` | Initialize MCP session (required first) |
| `tools/list` | List available tools |
| `tools/call` | Execute a tool |
| `ping` | Keep-alive ping |
| `notifications/initialized` | Client initialized notification |

## Hot Reload

Tools can be reloaded at runtime without server restart:

```bash
# Reload all namespaces
curl -X POST http://localhost:13000/api/reload \
  -H "Authorization: Bearer <token>"

# Reload specific namespace
curl -X POST http://localhost:13000/api/reload/shared \
  -H "Authorization: Bearer <token>"
```

## Adding New Tools

Tools are Python files in `tooldock_data/tools/{namespace}/`.

**Options to add tools:**
1. **File system**: Create `.py` file in namespace folder, then hot reload
2. **Admin UI**: Upload via http://localhost:13000 (Tools page)
3. **API**: POST to `/api/folders/{namespace}/files`

See [how-to-add-a-tool-with-a-llm.md](how-to-add-a-tool-with-a-llm.md) for detailed instructions on generating tools with an LLM.

## Client Configuration Examples

### LiteLLM

```yaml
mcp_servers:
  - server_name: "tooldock-shared"
    url: "http://localhost:13000/mcp/shared"
    api_key_header: "Authorization"
    api_key_value: "Bearer <token>"
```

### Claude Desktop

```json
{
  "mcpServers": {
    "tooldock": {
      "url": "http://localhost:13000/mcp/shared",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

### LM Studio

```json
{
  "mcpServers": {
    "tooldock": {
      "url": "http://localhost:13000/mcp/shared",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```
