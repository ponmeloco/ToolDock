# ToolDock Architecture

## Purpose

ToolDock is a multi-tenant MCP server that exposes Python tools in a controlled and machine-readable way.
It separates business logic from transport concerns and supports namespace-based routing for multi-tenant deployments.

## Core Components

- **Tool modules** defining contracts and handlers (`tooldock_data/tools/`)
- **ToolRegistry** with namespace support (`app/registry.py`)
- **Loader** for multi-folder discovery (`app/loader.py`)
- **Transport Layer** with multiple implementations (`app/transports/`)
- **Web GUI** for management (`app/web/`)
- **External Server Manager** for MCP Registry integration (`app/external/`)

## Design Principles

- Contracts over conventions
- One responsibility per tool
- Deterministic behavior
- Transport-agnostic tool logic
- DRY: Tools defined once, exposed via multiple transports
- Namespace isolation for multi-tenancy

---

## Transport Layer Architecture

The server implements a **triple-transport architecture**:

```
┌────────────────────────────────────────────────────────────────┐
│                     Shared Components                           │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐              │
│  │ToolRegistry │  │   Loader    │  │   Auth     │              │
│  │ (namespaces)│  │ (multi-dir) │  │            │              │
│  └──────┬──────┘  └──────┬──────┘  └────────────┘              │
│         │                │                                      │
│         ▼                ▼                                      │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Tool Definitions                           │    │
│  │         (tooldock_data/tools/{namespace}/*.py)           │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Transport 1:   │  │  Transport 2:   │  │  Transport 3:   │
│  OpenAPI (REST) │  │  MCP Streamable │  │  Web GUI        │
│                 │  │  HTTP           │  │                 │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Protocol:       │  │ Protocol:       │  │ Protocol:       │
│ HTTP/REST+JSON  │  │ JSON-RPC 2.0    │  │ HTTP/HTML+JSON  │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Port: 18006      │  │ Port: 18007      │  │ Port: 18080      │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Auth: Bearer    │  │ Auth: Bearer    │  │ Auth: Basic +   │
│                 │  │                 │  │       Bearer    │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ Use Case:       │  │ Use Case:       │  │ Use Case:       │
│ - OpenWebUI     │  │ - Claude        │  │ - Browser       │
│ - REST clients  │  │ - LiteLLM       │  │ - Management    │
│ - Web apps      │  │ - n8n           │  │ - Tool Upload   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## Namespace Routing

Each folder in `tooldock_data/tools/` becomes a separate MCP namespace:

```
tooldock_data/tools/
├── shared/           →  /mcp/shared
├── team1/            →  /mcp/team1
├── finance/          →  /mcp/finance
└── github/           →  /mcp/github (external)
```

### MCP Endpoint Structure (Strict Mode)

```
/mcp                    → Global endpoint (JSON-RPC 2.0 POST)
/mcp/namespaces         → List available namespaces
/mcp/{namespace}        → Namespace-specific endpoint (JSON-RPC 2.0 POST)
/mcp/info               → Non-standard discovery (GET)
/mcp/{namespace}/info   → Non-standard discovery (GET)
```

### Namespace Isolation

- Each namespace has its own set of tools
- `tools/list` on `/mcp/shared` returns only shared tools
- `tools/call` validates tool belongs to requested namespace
- External MCP servers register as separate namespaces

---

## Transport 1: OpenAPI (REST)

- **Protocol:** HTTP/REST with JSON
- **Location:** `app/transports/openapi_server.py`
- **Port:** 8006 (configurable via `OPENAPI_PORT`)
- **Use Case:** OpenWebUI, REST clients, web integrations
- **Authentication:** Bearer Token

**Endpoints:**
- `GET /health` - Health check
- `GET /tools` - List all tools (all namespaces)
- `POST /tools/{name}` - Execute a tool
- `GET /openapi.json` - OpenAPI specification

---

## Transport 2: MCP Streamable HTTP

- **Protocol:** JSON-RPC 2.0 over HTTP
- **Location:** `app/transports/mcp_http_server.py`
- **Port:** 8007 (configurable via `MCP_PORT`)
- **Use Case:** MCP clients (Claude Desktop, LiteLLM, n8n)
- **Authentication:** Bearer Token
- **Specification:** https://modelcontextprotocol.io/specification

**Endpoints (Strict MCP):**
- `GET /health` - Health check
- `GET /mcp/namespaces` - List namespaces
- `POST /mcp` - Global JSON-RPC 2.0 endpoint
- `POST /mcp/{namespace}` - Namespace-specific JSON-RPC
- `GET /mcp` - SSE stream (Accept: `text/event-stream`)
- `GET /mcp/{namespace}` - SSE stream (Accept: `text/event-stream`)
- `GET /mcp/info` - Non-standard discovery
- `GET /mcp/{namespace}/info` - Non-standard discovery

**MCP Methods:**
- `initialize` - Initialize session
- `notifications/initialized` - Notification after init (legacy `initialized` supported)
- `ping` - Keep-alive
- `tools/list` - List available tools
- `tools/call` - Execute a tool

**Strict MCP Notes:**
- GET endpoints return SSE streams (require `Accept: text/event-stream`)
- POST requests require `Accept: application/json` (include `text/event-stream` if you can handle streaming responses)
- JSON-RPC batching is rejected
- Notifications-only requests return **202** with no body
- `Origin` header is validated against `CORS_ORIGINS`
- `MCP-Protocol-Version` is validated if present; supported versions via `MCP_PROTOCOL_VERSIONS`

---

## Transport 3: Web GUI

- **Protocol:** HTTP/HTML + JSON API
- **Location:** `app/web/server.py`
- **Port:** 8080 (configurable via `WEB_PORT`)
- **Use Case:** Browser-based management
- **Authentication:** HTTP Basic Auth (browser) + Bearer Token (API)

**HTML Endpoints:**
- `GET /` - Dashboard
- `GET /health` - Health check (no auth)

**API Endpoints:**
- `GET /api/dashboard` - Dashboard data
- `GET /api/folders` - List namespaces
- `POST /api/folders` - Create namespace
- `DELETE /api/folders/{namespace}` - Delete namespace
- `GET /api/folders/{namespace}/tools` - List tools
- `POST /api/folders/{namespace}/tools` - Upload tool
- `DELETE /api/folders/{namespace}/tools/{file}` - Delete tool
- `GET /api/servers` - List external servers
- `POST /api/servers` - Add external server
- `DELETE /api/servers/{server_id}` - Remove external server

---

## Authentication

### Bearer Token Auth
- Used for OpenAPI and MCP endpoints
- Header: `Authorization: Bearer <token>`
- Token configured via `BEARER_TOKEN` env var
- Constant-time comparison to prevent timing attacks

### HTTP Basic Auth
- Used for Web GUI browser access
- Username: `admin` (configurable via `ADMIN_USERNAME`)
- Password: Same as `BEARER_TOKEN`
- Browser shows native login prompt

### Combined Auth (Web GUI API)
- `/api/*` endpoints accept both Basic and Bearer auth
- Allows browser access AND programmatic access

---

## External MCP Server Integration

External servers from the MCP Registry run as subprocesses:

```
ToolDock Container
├── Python Process (main)
│   ├── FastAPI (Ports 18006, 18007, 18080)
│   ├── Registry with Namespaces
│   └── MCPServerProxy Manager
│
└── Subprocesses (started via npx/uvx)
    ├── npx @modelcontextprotocol/server-github
    ├── npx @anthropic/mcp-server-mssql
    └── npx @modelcontextprotocol/server-filesystem
```

### Configuration

```yaml
# tooldock_data/external/config.yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}

  mssql:
    source: custom
    command: npx
    args: ["-y", "@anthropic/mcp-server-mssql"]
    env:
      MSSQL_CONNECTION_STRING: ${MSSQL_CONNECTION_STRING}
```

### Lifecycle
1. Container starts
2. `config.yaml` is read
3. For each enabled server: subprocess is started
4. MCPServerProxy connects via STDIO
5. Tools are discovered and registered under namespace

---

## Data Flow

### MCP Namespace Request Flow

```
Client JSON-RPC Request to /mcp/shared
     │
     ▼
┌─────────────┐
│ FastAPI     │
│ Auth Check  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Namespace   │
│ Validation  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ JSON-RPC    │
│ Router      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Namespace   │
│ Tool Filter │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Tool        │
│ Registry    │
│ .call()     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Tool        │
│ Handler     │
└─────────────┘
```

---

## Shared Components

Both transports use:

1. **Same `ToolRegistry`** (`app/registry.py`)
   - Namespace-aware registration
   - Singleton pattern via `get_registry()`
   - Thread-safe tool registration
   - Unified validation via Pydantic

2. **Same tool definitions** (`tooldock_data/tools/{namespace}/*.py`)
   - Tools defined once
   - Automatic discovery via `loader.py`
   - `register_tools(registry)` pattern

3. **Same validation logic**
   - Pydantic schemas with `extra="forbid"`
   - Consistent error handling

4. **Same execution handlers**
   - Async handlers
   - Consistent return types

---

## Configuration

Environment variables control behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_MODE` | `openapi` | `openapi`, `mcp-http`, `both`, `web-gui`, `all` |
| `DATA_DIR` | `./tooldock_data` | Base directory for all data |
| `OPENAPI_PORT` | `18006` | OpenAPI server port |
| `MCP_PORT` | `18007` | MCP server port |
| `WEB_PORT` | `18080` | Web GUI port |
| `BEARER_TOKEN` | - | Auth token (required) |
| `ADMIN_USERNAME` | `admin` | Web GUI username |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_RETENTION_DAYS` | `30` | Days to keep log files |
| `MCP_PROTOCOL_VERSION` | `2025-11-25` | Default MCP protocol version |
| `MCP_PROTOCOL_VERSIONS` | `2025-11-25,2025-03-26` | Comma-separated supported versions |
| `HOST_DATA_DIR` | `./tooldock_data` | Host path for UI display |

---

## Security Features

1. **Constant-time token comparison** - Prevents timing attacks
2. **Path traversal protection** - Validates filenames and paths
3. **Sensitive data masking** - Tokens/passwords hidden in API responses
4. **CORS configuration** - Configurable origins
5. **Tool validation** - AST-based validation for uploaded tools
6. **Namespace isolation** - Tools isolated per namespace

---

## Extensibility

### Adding a New Namespace

1. Create folder `tooldock_data/tools/myteam/`
2. Add Python tool files
3. Restart server
4. Access via `/mcp/myteam`

### Adding a New Transport

1. Create `app/transports/new_transport.py`
2. Implement `create_new_transport_app(registry: ToolRegistry) -> FastAPI`
3. Add to `main.py` with new `SERVER_MODE` option
4. Update `docker-compose.yml`

### Adding External MCP Servers

1. Edit `tooldock_data/external/config.yaml`
2. Add server configuration
3. Restart server
4. Access via `/mcp/{server_id}`
