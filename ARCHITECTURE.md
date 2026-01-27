# OmniMCP Architecture

## Purpose

OmniMCP is a capability layer that exposes Python tools in a controlled and machine-readable way.
It separates business logic from transport concerns such as OpenAPI or MCP.

## Core Components

- **Tool modules** defining contracts and handlers (`tools/`)
- **ToolRegistry** for validation and execution (`app/registry.py`)
- **Loader** for dynamic discovery (`app/loader.py`)
- **Transport Layer** with multiple implementations (`app/transports/`)

## Design Principles

- Contracts over conventions
- One responsibility per tool
- Deterministic behavior
- Transport-agnostic tool logic
- DRY: Tools defined once, exposed via multiple transports

---

## Transport Layer Architecture

The server implements a **dual-transport architecture**:

```
┌────────────────────────────────────────────────────┐
│                Shared Components                    │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │ ToolRegistry│  │   Loader    │  │   Errors   │ │
│  │ (singleton) │  │             │  │            │ │
│  └──────┬──────┘  └──────┬──────┘  └────────────┘ │
│         │                │                         │
│         ▼                ▼                         │
│  ┌────────────────────────────────────────────┐   │
│  │           Tool Definitions                  │   │
│  │         (tools/shared/*.py)                 │   │
│  └────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼                           ▼
┌─────────────────────┐   ┌─────────────────────┐
│   Transport 1:      │   │   Transport 2:      │
│   OpenAPI (REST)    │   │   MCP Streamable    │
│                     │   │   HTTP              │
├─────────────────────┤   ├─────────────────────┤
│ Protocol: HTTP/REST │   │ Protocol: JSON-RPC  │
│           + JSON    │   │           2.0       │
├─────────────────────┤   ├─────────────────────┤
│ Location:           │   │ Location:           │
│ app/transports/     │   │ app/transports/     │
│ openapi_server.py   │   │ mcp_http_server.py  │
├─────────────────────┤   ├─────────────────────┤
│ Port: 8006          │   │ Port: 8007          │
├─────────────────────┤   ├─────────────────────┤
│ Auth: Bearer Token  │   │ Auth: None (yet)    │
├─────────────────────┤   ├─────────────────────┤
│ Use Case:           │   │ Use Case:           │
│ - OpenWebUI         │   │ - Claude Desktop    │
│ - REST clients      │   │ - n8n               │
│ - Web integrations  │   │ - MCP clients       │
└─────────────────────┘   └─────────────────────┘
```

### Transport 1: OpenAPI (REST)

- **Protocol:** HTTP/REST with JSON
- **Location:** `app/transports/openapi_server.py`
- **Port:** 8006 (configurable via `OPENAPI_PORT`)
- **Use Case:** OpenWebUI, REST clients, web integrations
- **Authentication:** Bearer Token

**Endpoints:**
- `GET /health` - Health check
- `GET /tools` - List all tools
- `POST /tools/{name}` - Execute a tool
- `GET /openapi.json` - OpenAPI specification

### Transport 2: MCP Streamable HTTP

- **Protocol:** JSON-RPC 2.0 over HTTP
- **Location:** `app/transports/mcp_http_server.py`
- **Port:** 8007 (configurable via `MCP_PORT`)
- **Use Case:** MCP clients (Claude Desktop, n8n, etc.)
- **Specification:** https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http

**Endpoints:**
- `GET /health` - Health check
- `GET /mcp` - Server info
- `POST /mcp` - JSON-RPC 2.0 endpoint

**MCP Methods:**
- `initialize` - Initialize session
- `initialized` - Notification after init
- `ping` - Keep-alive
- `tools/list` - List available tools
- `tools/call` - Execute a tool

---

## Shared Components

Both transports use:

1. **Same `ToolRegistry`** (`app/registry.py`)
   - Singleton pattern via `get_registry()`
   - Thread-safe tool registration
   - Unified validation via Pydantic

2. **Same tool definitions** (`tools/shared/*.py`)
   - Tools defined once
   - Automatic discovery via `loader.py`
   - `register_tools(registry)` pattern

3. **Same validation logic**
   - Pydantic schemas with `extra="forbid"`
   - Consistent error handling

4. **Same execution handlers**
   - Async handlers
   - Consistent return types

This ensures **consistency** and **DRY principles**.

---

## Data Flow

### OpenAPI Request Flow

```
Client Request
     │
     ▼
┌─────────────┐
│ FastAPI     │
│ Middleware  │
│ (Auth)      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ OpenAPI     │
│ Endpoint    │
│ Handler     │
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

### MCP Request Flow

```
Client JSON-RPC Request
     │
     ▼
┌─────────────┐
│ FastAPI     │
│ /mcp        │
│ Endpoint    │
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
│ Method      │
│ Handler     │
│ (e.g.       │
│ tools/call) │
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

## Configuration

Environment variables control behavior:

| Variable | Description |
|----------|-------------|
| `SERVER_MODE` | `openapi`, `mcp-http`, or `both` |
| `TOOLS_DIR` | Path to tool modules |
| `OPENAPI_PORT` | OpenAPI server port |
| `MCP_PORT` | MCP server port |
| `BEARER_TOKEN` | Auth token for OpenAPI |

---

## Extensibility

### Adding a New Transport

1. Create `app/transports/new_transport.py`
2. Implement `create_new_transport_app(registry: ToolRegistry) -> FastAPI`
3. Add to `main.py` with new `SERVER_MODE` option
4. Update `docker-compose.yml`

### Adding New MCP Methods

1. Add handler function in `mcp_http_server.py`
2. Register in `METHOD_HANDLERS` dict
3. Document in this file
