# Tool Server

A dual-transport tool server that exposes Python-based tools to LLMs and agent systems via both **OpenAPI/REST** and **MCP (Model Context Protocol)**.

## Core Documents

- [Architecture overview](ARCHITECTURE.md)
- [LLM instructions](LLM_INSTRUCTIONS.md)
- [Tool template](tool_template.py)

## Architecture

This server supports **TWO transport mechanisms**:

```
┌─────────────────────────────────────────────────────────┐
│              Shared Tool Registry                        │
│                (app/registry.py)                        │
│        Tools from tools/shared/*.py loaded              │
└────────────┬───────────────────┬────────────────────────┘
             │                   │
   ┌─────────▼─────────┐   ┌────▼─────────────────┐
   │   Transport 1:    │   │   Transport 2:       │
   │   OpenAPI/REST    │   │   MCP Streamable     │
   │   (FastAPI)       │   │   HTTP               │
   │                   │   │                      │
   │   Port: 8006      │   │   Port: 8007         │
   │                   │   │                      │
   │   For:            │   │   For:               │
   │   - OpenWebUI     │   │   - Claude Desktop   │
   │   - REST APIs     │   │   - n8n              │
   │   - Web clients   │   │   - MCP Clients      │
   └───────────────────┘   └──────────────────────┘
```

Both transports share the same tool registry, so **tools only need to be defined once**.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Or: Python 3.11+

### Option 1: OpenAPI only (for OpenWebUI)

```bash
# Using Docker
docker compose up tool-server-openapi

# Or locally
SERVER_MODE=openapi python main.py
```

Access at: http://localhost:8006

### Option 2: MCP only (for Claude Desktop, n8n)

```bash
# Using Docker
docker compose up tool-server-mcp-http

# Or locally
SERVER_MODE=mcp-http python main.py
```

Access at: http://localhost:8007

### Option 3: Both servers (maximum flexibility)

```bash
# Using Docker
docker compose --profile combined up tool-server-both

# Or locally
SERVER_MODE=both python main.py
```

Access at:
- OpenAPI: http://localhost:8006
- MCP: http://localhost:8007

## Connecting Clients

### OpenWebUI

1. Go to Settings > Connections > OpenAPI
2. Add server URL: `http://localhost:8006`
3. Add Bearer token from your `.env` file

### Claude Desktop

Add to `~/.config/Claude/claude_desktop_config.json` (Linux) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "my-tools": {
      "url": "http://localhost:8007/mcp",
      "transport": "http"
    }
  }
}
```

### n8n

Use the MCP Node with:
- URL: `http://localhost:8007/mcp`
- Transport: HTTP

## Runtime Endpoints

### OpenAPI Server (Port 8006)

| Endpoint | Description |
|----------|-------------|
| GET /health | Health check |
| GET /openapi.json | OpenAPI specification |
| GET /tools | List registered tools (authenticated) |
| POST /tools/{tool_name} | Execute a tool (authenticated) |

### MCP Server (Port 8007)

| Endpoint | Method | Description |
|----------|--------|-------------|
| GET /health | GET | Health check |
| GET /mcp | GET | Server info and available methods |
| POST /mcp | POST | JSON-RPC 2.0 endpoint for MCP requests |

**MCP Methods:**
- `initialize` - Initialize MCP session
- `tools/list` - List available tools
- `tools/call` - Execute a tool
- `ping` - Ping server

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_MODE` | `openapi` | Server mode: `openapi`, `mcp-http`, or `both` |
| `TOOLS_DIR` | `./tools` | Directory containing tool modules |
| `BEARER_TOKEN` | - | Authentication token for OpenAPI |
| `OPENAPI_PORT` | `8006` | Port for OpenAPI server |
| `MCP_PORT` | `8007` | Port for MCP server |
| `HOST` | `0.0.0.0` | Bind address |

## Adding a New Tool

1. Create a new Python file under `tools/<domain>/`
2. Define a Pydantic input model with `extra="forbid"`
3. Implement an async handler function
4. Register the tool using `register_tools(registry)`
5. Restart the server

Example (`tools/shared/my_tool.py`):

```python
from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class MyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="The query to process")

async def my_tool_handler(payload: MyToolInput) -> dict:
    return {"result": f"Processed: {payload.query}"}

def register_tools(registry: ToolRegistry) -> None:
    MyToolInput.model_rebuild(force=True)

    registry.register(
        ToolDefinition(
            name="my_tool",
            description="Processes a query and returns results",
            input_model=MyToolInput,
            handler=my_tool_handler,
        )
    )
```

## Security Model

- **OpenAPI**: Bearer token authentication (via `BEARER_TOKEN` env var)
- **MCP**: Currently no authentication (run in trusted network)
- All tool execution endpoints are protected on OpenAPI
- Secrets must never be committed to Git

## Repository Structure

```
.
├── README.md                    # This file
├── ARCHITECTURE.md              # Architecture principles
├── LLM_INSTRUCTIONS.md          # Rules for LLM behavior
├── tool_template.py             # Template for new tools
├── main.py                      # Main entrypoint
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── auth.py                  # Authentication logic
│   ├── errors.py                # Error types
│   ├── loader.py                # Dynamic tool loading
│   ├── registry.py              # Tool registry (shared)
│   └── transports/
│       ├── __init__.py
│       ├── openapi_server.py    # OpenAPI transport
│       └── mcp_http_server.py   # MCP Streamable HTTP transport
└── tools/
    └── shared/
        └── example.py           # Example tool
```

## Testing

Run the test script to verify both transports:

```bash
./test_both_transports.sh
```

Or test manually:

```bash
# OpenAPI Health
curl http://localhost:8006/health

# OpenAPI List Tools
curl http://localhost:8006/tools -H "Authorization: Bearer change_me_openapi"

# MCP Health
curl http://localhost:8007/health

# MCP List Tools
curl -X POST http://localhost:8007/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## License

MIT
