# ToolDock - Claude Code Instructions

## Project Overview

**ToolDock** is a multi-tenant MCP server with namespace-based routing, exposing Python tools via **Tool API (OpenAPI transport)**, **MCP**, and **Web GUI**. MCP runs in **strict spec mode** while keeping namespace endpoints. The core principle: **Tools are code-defined capabilities, not prompt-based logic.**

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│   Admin UI       │     │         ToolDock Backend             │
│   (React/nginx)  │     ├─────────────────────────────────────┤
│  Port 13000      │────→│  Internal: 8006 Tool API            │
│  /api/*          │     │  Internal: 8007 MCP HTTP            │
│  /openapi/*      │     │  Internal: 8080 Backend API         │
│  /mcp/*          │     │                                     │
└──────────────────┘     ├─────────────────────────────────────┤
                         │  /mcp/shared    → shared/ tools     │
LiteLLM ────────────────→│  /mcp/team1     → team1/ tools      │
Claude Desktop ─────────→│  /mcp/github    → GitHub MCP        │
                         └─────────────────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         │      tooldock_data/ (Volume)   │
                         ├───────────────────────────────┤
                         │  tools/shared/*.py            │
                         │  tools/team1/*.py             │
                         │  external/servers/{ns}/       │
                         │    config.yaml                │
                         │  logs/YYYY-MM-DD.jsonl        │
                         │  metrics.sqlite               │
                         │  venvs/{namespace}/           │
                         └───────────────────────────────┘
```

**Two-Container Architecture:**
- `tooldock-backend`: Python FastAPI (all APIs)
- `tooldock-gateway`: React + nginx (Admin UI + reverse proxy)

All three transports share the same tool registry — **define once, use everywhere**.

## Key Files & Directories

### Core Application
| File | Purpose |
|------|---------|
| `app/registry.py` | Central tool registry (DO NOT BREAK!) |
| `app/loader.py` | Loads tools from `tooldock_data/tools/` |
| `app/reload.py` | Hot reload functionality |
| `app/auth.py` | Bearer token authentication |
| `app/metrics_store.py` | Metrics ingestion + SQLite persistence |
| `app/deps.py` | Per-namespace venv management + npm package validation |
| `app/transports/` | OpenAPI and MCP transport implementations |
| `app/web/` | Backend API server and routes |
| `app/external/` | External MCP + FastMCP server integration |
| `main.py` | Server entrypoint |

### Tests
| Directory | Purpose |
|-----------|---------|
| `tests/unit/` | Unit tests (~250 tests) |
| `tests/integration/` | Integration tests (~240 tests) |
| `tests/fixtures/` | Sample tools for testing |
| `conftest.py` | Shared pytest fixtures |

## Tool Definition Pattern

```python
from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")  # REQUIRED!
    field: str = Field(..., description="...")

async def handler(payload: ToolInput) -> dict:
    return {"result": "..."}

def register_tools(registry: ToolRegistry) -> None:
    ToolInput.model_rebuild(force=True)  # Required for hot reload
    registry.register(ToolDefinition(
        name="tool_name",
        description="Clear description",
        input_model=ToolInput,
        handler=handler,
    ))
```

## Style Guidelines

- **Type hints everywhere** - `def func(arg: str) -> dict:`
- **Async for I/O** - All handlers, all external calls
- **Pydantic validation** - Never manual dict parsing
- **ConfigDict** - Use `model_config = ConfigDict(...)` not `class Config:`
- **Logging** - Use `logger.info/error/debug`, not `print()`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BEARER_TOKEN` | (required) | API authentication token |
| `SERVER_MODE` | `all` | openapi, mcp-http, web-gui, both, all |
| `ADMIN_PORT` | `13000` | Single exposed gateway port (Admin UI + `/api` + `/openapi` + `/mcp`) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `DATA_DIR` | `tooldock_data` | Data directory path |
| `LOG_RETENTION_DAYS` | `30` | Days to keep log files |
| `METRICS_RETENTION_DAYS` | `30` | Days to keep metrics in SQLite |
| `MCP_PROTOCOL_VERSION` | `2024-11-05` | Default MCP protocol version |
| `MCP_PROTOCOL_VERSIONS` | `2024-11-05,2025-03-26,2025-11-25` | Comma-separated supported versions |
| `HOST_DATA_DIR` | `./tooldock_data` | Host path for UI display |
| `FASTMCP_DEMO_ENABLED` | `false` | Enable/disable seeded demo FastMCP server |
| `FASTMCP_INSTALLER_ENABLED` | `true` | Enable/disable built-in installer MCP server |
| `FASTMCP_INSTALLER_NAMESPACE` | `tooldock-installer` | Namespace for protected installer server |

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/test_registry.py -v
```

## Start Script

```bash
# Normal start (uses cached images)
./start.sh

# Force rebuild all images
./start.sh --rebuild
./start.sh -r

# Skip tests during startup (faster bootstrap)
./start.sh --skip-tests
```

The script:
- Creates `.env` from `.env.example` if missing
- Creates data directories with correct permissions
- Builds Docker images (with spinner animation)
- Starts containers and runs health checks
- Runs pytest if installed (skipped on production)

## Docker Commands

```bash
# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Rebuild specific container
docker compose build tooldock-gateway
docker compose up -d tooldock-gateway

# Stop all
docker compose down
```

## Key Features

### Hot Reload
```bash
curl -X POST http://localhost:13000/api/reload \
  -H "Authorization: Bearer change_me"
```

### Playground (Admin UI)
- Test tools via OpenAPI or MCP (real servers)
- JSON input editor with syntax highlighting
- Real-time execution results

### MCP Strict Mode Notes
- Authentication is enforced on all MCP endpoints, including localhost traffic.
- Clients must send `Authorization: Bearer <BEARER_TOKEN>` for both `GET /mcp*` (SSE) and `POST /mcp*` (JSON-RPC).
- GET endpoints return SSE streams (require `Accept: text/event-stream`)
- For `POST /mcp*`, `Accept: application/json` is recommended; missing `Accept` is accepted
- JSON-RPC batching is rejected
- Notifications-only requests return **202** with no body
- `Origin` header validated against `CORS_ORIGINS`
- `MCP-Protocol-Version` accepted if present (unsupported values ignored for compatibility)

### Persistent Logging
- Daily log files: `DATA_DIR/logs/YYYY-MM-DD.jsonl`
- Auto-cleanup after `LOG_RETENTION_DAYS`
- In-memory buffer for live viewing

### Metrics
- Hybrid metrics store: in-memory queue + `DATA_DIR/metrics.sqlite`
- Dashboard pulls from `GET /api/admin/metrics`
- Auto-cleanup after `METRICS_RETENTION_DAYS`

### FastMCP External Servers
- Managed via `app/external/fastmcp_manager.py` (registry ingest + lifecycle)
- Exposed via `/api/fastmcp/*` routes (Admin UI → MCP Servers page)
- Installation methods:
  - **Registry**: Search and install from MCP Registry (PyPI/npm packages)
  - **Repo URL**: Install from git repository URL
  - **Manual**: Add servers using Claude Desktop config format (command, args, env)
  - **From Config**: Paste Claude Desktop JSON config
- Safety checks:
  - `POST /api/fastmcp/safety/check` returns risk summary/checklist
  - `blocked=true` indicates install should not continue
- Package type handling:
  - **PyPI**: Runs with `uvx <package>` (uv handles isolation, no venv needed)
  - **npm**: Validates via `npm view`, runs with `npx -y <package>` (no venv needed)
  - **Repo**: Clones git repo, user configures startup command via detail panel
- Provenance tracking:
  - `package_type`: npm, pypi, oci, remote, repo, manual, system
  - `source_url`: GitHub/registry URL for reference
  - Type badges shown in search results and detail panel
- Built-in installer server:
  - Module: `app.external.installer_mcp_server`
  - Namespace defaults to `tooldock-installer`
  - Protected against deletion via API/UI
- Server detail panel with:
  - Config file editor (YAML/JSON syntax highlighting)
  - Editable start command (command, args, env)
  - Start/stop controls; delete disabled for system server
- Config files stored in `DATA_DIR/external/servers/{namespace}/`

### Unified Namespaces
- `/api/admin/namespaces` returns all namespace types:
  - **Native**: Python tools from `tooldock_data/tools/`
  - **FastMCP**: MCP servers from registry or manual config
- Admin UI Namespaces page shows all types with status badges

## Common Pitfalls

- Don't block event loop (use async!)
- Don't use `print()` - use `logger`
- Don't use bare `except:` - catch specific errors
- Don't use `class Config:` - use `model_config = ConfigDict(...)`
- Always call `model_rebuild(force=True)` in `register_tools()`

## Before Committing

1. Run `pytest tests/ -v`
2. Test manually with curl
3. Check `docker compose logs -f`
4. Review `git diff`
