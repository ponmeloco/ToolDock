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

> **Disclaimer:** ToolDock is still under active development and best treated as a demo/preview.  
> Use at your own risk, especially in production environments.

---

## Quickstart

```bash
# Clone and start
git clone https://github.com/ponmeloco/ToolDock.git
cd ToolDock
./start.sh

# Force rebuild images
./start.sh --rebuild

# Faster first boot (skip pytest during startup)
./start.sh --skip-tests
```

Or manually:

```bash
cp .env.example .env
nano .env  # Set BEARER_TOKEN
docker compose up -d
```

**Verify:**

```bash
curl http://localhost:13000                 # Admin UI
curl http://localhost:13000/openapi/health  # Tool API via Admin gateway
curl http://localhost:13000/mcp/namespaces  # MCP via Admin gateway
curl http://localhost:13000/api/admin/health
```

ToolDock can optionally install and auto-start a demo FastMCP server
from the modelcontextprotocol/servers repo (time server) when
`FASTMCP_DEMO_ENABLED=true`. Configure via `FASTMCP_DEMO_*` in `.env`.
ToolDock also seeds a protected built-in installer server (`tooldock-installer`) for LLM-driven install workflows.

---

## Screenshots

Screenshots (from `docs/images/`):

### Admin Dashboard
![Admin Dashboard](docs/images/Dashboard.png)
### Playground
![Playground](docs/images/Playground.png)
### FastMCP Registry
![FastMCP Registry](docs/images/FastMCP.png)
### Logs
![Logs](docs/images/Logs.png)
### Namespaces Tool Create/Edit
![Namespaces](docs/images/Namespaces_Tool_Create_Edit.png)

---

## Troubleshooting

### Buildx Permission Error

If `./start.sh --rebuild` fails with:

```
failed to update builder last activity time: ... permission denied
```

It means Docker Buildx created files in `~/.docker` as `root` (often from a past `sudo docker ...` run).  
Fix by resetting ownership, then retry:

```bash
sudo chown -R $USER:$USER ~/.docker
./start.sh --rebuild
```

This only fixes Docker’s local metadata directory; it does **not** affect your ToolDock data in `tooldock_data/`.

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
| **Metrics** | Error rates + tool call counts via SQLite + in-memory queue |
| **MCP Servers** | Install from registry, repo URL, or manual command |
| **Safety Checks** | Pre-install risk assessment for server onboarding |
| **System Installer** | Built-in protected server for MCP-assisted install workflows |
| **Config Editor** | Edit server configs with YAML/JSON syntax highlighting |
| **Unified Namespaces** | View all namespace types (native, fastmcp) |

---

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│   Admin UI       │     │         ToolDock Backend             │
│   (React)        │     ├─────────────────────────────────────┤
│  Port 13000      │────→│  Internal: 8006 Tool API            │
│  /api/*          │     │  Internal: 8007 MCP HTTP            │
│  /openapi/*      │     │  Internal: 8080 Backend API         │
│  /mcp/*          │     │                                     │
└──────────────────┘     │                                     │
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

# Optional - Single Exposed Port
ADMIN_PORT=13000

# Optional - Logging
LOG_RETENTION_DAYS=30  # Auto-delete logs after N days
METRICS_RETENTION_DAYS=30  # SQLite metrics retention window

# Optional - MCP Protocol (strict mode)
MCP_PROTOCOL_VERSION=2024-11-05
MCP_PROTOCOL_VERSIONS=2024-11-05,2025-03-26

# Optional - Host display (Admin UI)
HOST_DATA_DIR=./tooldock_data

# Optional - External MCP
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# Optional - Built-in installer server
FASTMCP_INSTALLER_ENABLED=true
FASTMCP_INSTALLER_NAMESPACE=tooldock-installer
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

### FastMCP (Recommended)

Install FastMCP servers and expose them via namespaces.
Use the **MCP Servers** page in the Admin UI to search, install, start, stop, and configure servers.

**Installation methods:**

1. **From Registry** - Search the MCP Registry for PyPI/npm packages:
   - Search by name in the Admin UI (results show type badges: npm/pypi/repo)
   - Select a server and choose a namespace
   - Click Install to download and configure
   - **PyPI** packages run via `uvx <package>` (uv handles isolation, no venv needed)
   - **npm** packages are validated via `npm view` and run via `npx -y <package>` (no venv needed)
   - **Repo** packages clone the git repo; you configure the startup command in the detail panel

2. **From Repository URL** - Install directly from git repository:
   - Provide `repo_url` and namespace (optional entrypoint/server_name)
   - Review safety check before install
   - Configure runtime command/env in the detail panel if needed

3. **Manual Server** - Add servers using Claude Desktop config format:
   - Specify command (e.g., `python`, `node`, `npx`)
   - Add arguments (e.g., `-m my_module --config config.yaml`)
   - Set environment variables (e.g., `API_KEY=xxx`)

**Safety-first flow:**
- Run `POST /api/fastmcp/safety/check` before install (UI does this for registry/repo).
- If `blocked=true`, resolve failing checks before installation.

**Built-in installer server:**
- Namespace: `tooldock-installer` (configurable).
- Package type: `system`.
- Protected from deletion via API/UI, but start/stop/config updates are allowed.

**Server Management:**

Click on any installed server to open the detail panel:
- View server status, PID, port, and provenance (package type + source URL)
- Edit start command (command, args, env)
- Edit config files with syntax highlighting (YAML/JSON)
- Start, stop, or delete the server (with confirmation dialogs)

Config files are stored in `tooldock_data/external/servers/{namespace}/`.

The default database is SQLite at `DATA_DIR/db/tooldock.db`
(`./tooldock_data/db/tooldock.db` for local runs, `/data/db/tooldock.db` in Docker). You can switch to Postgres via:

```
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/tooldock
```

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
curl -X POST http://localhost:13000/api/reload/shared \
  -H "Authorization: Bearer change_me"
```

---

## Dependencies (Per Namespace)

Each namespace gets its own Python venv stored in `tooldock_data/venvs/{namespace}`.  
Install dependencies via the Admin UI **Tools → Dependencies**, or via API:

```bash
curl -X POST http://localhost:13000/api/folders/shared/files/deps/install \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"requirements": "requests==2.32.0"}'
```

Create/Delete venv:

```bash
curl -X POST http://localhost:13000/api/folders/shared/files/deps/create \
  -H "Authorization: Bearer change_me"

curl -X POST http://localhost:13000/api/folders/shared/files/deps/delete \
  -H "Authorization: Bearer change_me"
```

After install, ToolDock auto-reloads the namespace so imports work immediately.

Uninstall (pip/setuptools/wheel are protected):

```bash
curl -X POST http://localhost:13000/api/folders/shared/files/deps/uninstall \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"packages": ["requests"]}'
```

---

## Connecting Clients

### LiteLLM

```yaml
mcp_servers:
  - server_name: "tooldock"
    # If LiteLLM runs in Docker on the same network, use the service name:
    url: "http://tooldock-backend:8007/mcp/shared"
    api_key_header: "Authorization"
    api_key_value: "Bearer change_me"
```

If LiteLLM runs on the host (not in Docker), use:
`http://localhost:13000/mcp/shared`

### Claude Desktop

Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tooldock": {
      "url": "http://localhost:13000/mcp/shared",
      "headers": {
        "Authorization": "Bearer change_me"
      }
    }
  }
}
```

### LM Studio

Add to LM Studio MCP config:

```json
{
  "mcpServers": {
    "tooldock": {
      "url": "http://localhost:13000/mcp/shared",
      "headers": {
        "Authorization": "Bearer change_me"
      }
    }
  }
}
```

---

## API Reference

### Tool API (OpenAPI transport)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/openapi/health` | GET | Health check via Admin gateway (13000) |
| `/openapi/tools` | GET | List tools via Admin gateway (13000) |
| `/openapi/tools/{name}` | POST | Execute tool via Admin gateway (13000) |

### MCP (Streamable HTTP)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp/namespaces` | GET | List namespaces via Admin gateway (13000) |
| `/mcp` | POST | JSON-RPC endpoint (all namespaces) |
| `/mcp/{namespace}` | POST | JSON-RPC endpoint (namespace) |
| `/mcp` | GET | SSE stream for server-initiated messages (all namespaces) |
| `/mcp/{namespace}` | GET | SSE stream for server-initiated messages (namespace) |
| `/mcp/sse` | GET/POST | Compatibility alias for `/mcp` |
| `/mcp/{namespace}/sse` | GET/POST | Compatibility alias for `/mcp/{namespace}` |
| `/mcp/info` | GET | Non-standard discovery |
| `/mcp/{namespace}/info` | GET | Non-standard discovery |

### Backend API (via gateway)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/folders` | GET | List namespaces |
| `/api/folders/{ns}/files` | GET/POST | List/upload tools |
| `/api/reload` | POST | Hot reload all |
| `/api/reload/{ns}` | POST | Hot reload namespace |
| `/api/admin/logs` | GET | View logs |
| `/api/admin/logs/files` | GET | List log files |
| `/api/admin/metrics` | GET | Metrics for dashboard (error rates + tool calls) |
| `/api/admin/namespaces` | GET | List all namespaces (native, fastmcp) |
| `/api/playground/tools` | GET | List tools for playground |
| `/api/playground/execute` | POST | Execute tool (OpenAPI/MCP via real servers) |

### FastMCP API (via gateway)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/fastmcp/registry/servers` | GET | Search MCP Registry |
| `/api/fastmcp/registry/health` | GET | Check registry connectivity |
| `/api/fastmcp/safety/check` | POST | Run install safety assessment |
| `/api/fastmcp/servers` | GET | List installed servers |
| `/api/fastmcp/servers` | POST | Install from registry |
| `/api/fastmcp/servers/repo` | POST | Install from repo URL |
| `/api/fastmcp/servers/manual` | POST | Add manual server |
| `/api/fastmcp/servers/from-config` | POST | Add from Claude Desktop config |
| `/api/fastmcp/servers/{id}` | GET | Get server details |
| `/api/fastmcp/servers/{id}` | PUT | Update server config |
| `/api/fastmcp/servers/{id}` | DELETE | Delete server |
| `/api/fastmcp/servers/{id}/start` | POST | Start server |
| `/api/fastmcp/servers/{id}/stop` | POST | Stop server |
| `/api/fastmcp/sync` | POST | Re-sync running servers into tool registry |
| `/api/fastmcp/servers/{id}/config` | GET | Get config file content |
| `/api/fastmcp/servers/{id}/config` | PUT | Update config file |
| `/api/fastmcp/servers/{id}/config/files` | GET | List config files |

---

## MCP Strict Mode Notes

ToolDock implements the **MCP Streamable HTTP** transport per spec revisions `2024-11-05` and `2025-03-26`.

- Authentication is enforced for all MCP endpoints, including `localhost`.
- Clients must send `Authorization: Bearer <BEARER_TOKEN>` on both `GET /mcp*` (SSE) and `POST /mcp*` (JSON-RPC).
- Missing/invalid auth returns **401** even from `localhost`.
- `POST /mcp*` returns JSON-RPC responses as `Content-Type: application/json` (HTTP body).
- `GET /mcp*` opens SSE streams for **server-initiated messages only** (requires `Accept: text/event-stream`). POST responses are never echoed to GET streams, per spec.
- For `POST /mcp*`, `Accept: application/json` is recommended; missing `Accept` is also accepted.
- JSON-RPC batching is rejected (returns `-32600`).
- Notifications-only requests return **202** with no body.
- `Mcp-Session-Id` header is included on all responses; stable per server process.
- `Origin` header is validated against `CORS_ORIGINS`.
- `MCP-Protocol-Version` header is accepted if present. Unsupported values are ignored for compatibility.
- Protocol version negotiation happens via `initialize.params.protocolVersion` (supported: `2024-11-05`, `2025-03-26`; configurable via `MCP_PROTOCOL_VERSIONS`).

---

## Metrics

- Metrics are aggregated from a hybrid in-memory queue + SQLite store at `tooldock_data/metrics.sqlite`.
- Dashboard reads `GET /api/admin/metrics` for error rates and tool call counts.
- Retention is controlled by `METRICS_RETENTION_DAYS` (default 30 days).

---

## Testing

```bash
# Run all tests
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
