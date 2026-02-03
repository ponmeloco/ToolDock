<p align="center">
  <h1 align="center">ToolDock</h1>
  <p align="center">
    <strong>One Server. Every Protocol. All Your Tools.</strong>
  </p>
  <p align="center">
    Multi-tenant MCP server with namespace-based routing, exposing Python tools via <b>OpenAPI</b>, <b>MCP</b>, and <b>Web GUI</b>.
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/MCP-Streamable_HTTP-purple.svg" alt="MCP Streamable HTTP">
  <img src="https://img.shields.io/badge/OpenAPI-3.0-green.svg" alt="OpenAPI 3.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License">
</p>

---

## Quickstart

```bash
# Clone and start
git clone https://github.com/ponmeloco/ToolDock.git
cd ToolDock
./start.sh

# Force rebuild images
./start.sh --rebuild
```

Or manually:

```bash
cp .env.example .env
nano .env  # Set BEARER_TOKEN
docker compose up -d
```

**Verify:**

```bash
curl http://localhost:18006/health   # OpenAPI
curl http://localhost:18007/health   # MCP
curl http://localhost:13000          # Admin UI
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Admin UI** | React dashboard with code editor, playground, and logs |
| **Multi-Tenant** | Each folder becomes a separate MCP endpoint |
| **Dual Transport** | OpenAPI + MCP from the same codebase |
| **Hot Reload** | Reload tools without server restart |
| **Playground** | Test tools via OpenAPI or MCP (real servers) |
| **Persistent Logs** | Daily JSON log files with auto-cleanup |
| **Metrics** | Fast dashboard metrics via SQLite + in-memory queue |
| **External MCP** | Integrate GitHub, Filesystem, etc. from MCP Registry |
| **Metrics** | Error rates + tool call counts via `/api/admin/metrics` |

---

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│   Admin UI       │     │         ToolDock Backend             │
│   (React)        │     ├─────────────────────────────────────┤
│  Port 13000      │────→│  Port 18006 → OpenAPI/REST          │
│                  │     │  Port 18007 → MCP HTTP              │
└──────────────────┘     │  Port 18080 → Backend API           │
                         ├─────────────────────────────────────┤
LiteLLM ────────────────→│  /mcp/shared    → shared/ tools     │
Claude Desktop ─────────→│  /mcp/team1     → team1/ tools      │
                         └─────────────────────────────────────┘
```

---

## Configuration

### Environment Variables (.env)

```bash
# Required
BEARER_TOKEN=your_secure_token_here

# Optional - Ports
OPENAPI_PORT=18006
MCP_PORT=18007
WEB_PORT=18080
ADMIN_PORT=13000

# Optional - Logging
LOG_RETENTION_DAYS=30  # Auto-delete logs after N days
METRICS_RETENTION_DAYS=30  # SQLite metrics retention window

# Optional - MCP Protocol (strict mode)
MCP_PROTOCOL_VERSION=2025-11-25
MCP_PROTOCOL_VERSIONS=2025-11-25,2025-03-26

# Optional - Host display (Admin UI)
HOST_DATA_DIR=./tooldock_data

# Optional - External MCP
GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

---

## Namespace Routing

Each folder in `tooldock_data/tools/` becomes a separate endpoint:

| Folder | MCP Endpoint |
|--------|--------------|
| `tools/shared/` | `/mcp/shared` |
| `tools/team1/` | `/mcp/team1` |
| `tools/finance/` | `/mcp/finance` |

---

## External MCP Servers

Configure external servers in `tooldock_data/external/config.yaml` (or `$DATA_DIR/external/config.yaml`) and reload without restart:

```bash
curl -X POST http://localhost:18080/api/servers/reload \
  -H "Authorization: Bearer change_me"
```

These servers are exposed as namespaces like `/mcp/github`.

---

## Adding Tools

### Via Admin UI

1. Open http://localhost:13000
2. **Tools** → select namespace → **New Tool**
3. Edit the template → **Save** (valid code required; auto-reloads)

### Via File

Create `tooldock_data/tools/shared/my_tool.py`:

```python
from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class MyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., description="The query")

async def handler(payload: MyToolInput) -> dict:
    return {"result": f"Processed: {payload.query}"}

def register_tools(registry: ToolRegistry) -> None:
    MyToolInput.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="my_tool",
        description="Processes a query",
        input_model=MyToolInput,
        handler=handler,
    ))
```

Then reload:

```bash
curl -X POST http://localhost:18080/api/reload/shared \
  -H "Authorization: Bearer change_me"
```

---

## Dependencies (Per Namespace)

Each namespace gets its own Python venv stored in `tooldock_data/venvs/{namespace}`.  
Install dependencies via the Admin UI **Tools → Dependencies**, or via API:

```bash
curl -X POST http://localhost:18080/api/folders/shared/tools/deps/install \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"packages": ["requests==2.32.0"]}'
```

Uninstall:

```bash
curl -X POST http://localhost:18080/api/folders/shared/tools/deps/uninstall \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"packages": ["requests"]}'
```

After install, ToolDock auto-reloads the namespace so imports work immediately.

---

## Connecting Clients

### LiteLLM

```yaml
mcp_servers:
  - server_name: "tooldock"
    url: "http://localhost:18007/mcp/shared"
    api_key_header: "Authorization"
    api_key_value: "Bearer change_me"
```

### Claude Desktop

Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tooldock": {
      "url": "http://localhost:18007/mcp/shared",
      "headers": {
        "Authorization": "Bearer change_me"
      }
    }
  }
}
```

---

## API Reference

### OpenAPI (Port 18006)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/tools` | GET | List tools |
| `/tools/{name}` | POST | Execute tool |

### MCP (Port 18007)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/mcp/namespaces` | GET | List namespaces |
| `/mcp` | POST | JSON-RPC endpoint (all namespaces) |
| `/mcp/{namespace}` | POST | JSON-RPC endpoint (namespace) |
| `/mcp/info` | GET | Non-standard discovery |
| `/mcp/{namespace}/info` | GET | Non-standard discovery |

### Backend API (Port 18080)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/folders` | GET | List namespaces |
| `/api/folders/{ns}/tools` | GET/POST | List/upload tools |
| `/api/reload` | POST | Hot reload all |
| `/api/reload/{ns}` | POST | Hot reload namespace |
| `/api/admin/logs` | GET | View logs |
| `/api/admin/logs/files` | GET | List log files |
| `/api/admin/metrics` | GET | Metrics for dashboard (error rates + tool calls) |
| `/api/playground/tools` | GET | List tools for playground |
| `/api/playground/execute` | POST | Execute tool (OpenAPI/MCP via real servers) |

---

## MCP Strict Mode Notes

- `GET /mcp` and `GET /mcp/{namespace}` open SSE streams (requires `Accept: text/event-stream`).
- POST requests require `Accept: application/json` (include `text/event-stream` if you can handle streaming responses).
- JSON-RPC batching is rejected.
- Notifications-only requests return **202** with no body.
- `Origin` header is validated against `CORS_ORIGINS`.
- `MCP-Protocol-Version` is validated if present; supported versions configured via `MCP_PROTOCOL_VERSIONS`.

---

## Metrics

- Metrics are aggregated from a hybrid in-memory queue + SQLite store at `tooldock_data/metrics.sqlite`.
- Dashboard reads `GET /api/admin/metrics` for error rates and tool call counts.
- Retention is controlled by `METRICS_RETENTION_DAYS` (default 30 days).

---

## Testing

```bash
# Run all tests (420+)
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Install test dependencies (optional, for development)
pip install pytest pytest-asyncio pytest-cov
```

> **Note:** Tests are skipped automatically on production servers without pytest installed.
> When using `./start.sh`, tests run **inside the backend container** (Python 3.12) to avoid host interpreter incompatibilities.

---

## License

MIT License - see [LICENSE](LICENSE) for details.
