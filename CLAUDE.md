# OmniMCP - Claude Code Instructions

## Project Overview

**OmniMCP** is a multi-tenant MCP server with namespace-based routing, exposing Python tools via **OpenAPI**, **MCP**, and **Web GUI**. The core principle: **Tools are code-defined capabilities, not prompt-based logic.**

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│   Admin UI       │     │         OmniMCP Backend             │
│   (React/nginx)  │     ├─────────────────────────────────────┤
│                  │     │  Port 8006 → OpenAPI/REST           │
│  Port 3000       │────→│  Port 8007 → MCP HTTP               │
│                  │     │  Port 8080 → Backend API            │
└──────────────────┘     ├─────────────────────────────────────┤
                         │  /mcp/shared    → shared/ tools     │
LiteLLM ────────────────→│  /mcp/team1     → team1/ tools      │
Claude Desktop ─────────→│  /mcp/github    → GitHub MCP        │
                         └─────────────────────────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         │      omnimcp_data/ (Volume)   │
                         ├───────────────────────────────┤
                         │  tools/shared/*.py            │
                         │  tools/team1/*.py             │
                         │  external/config.yaml         │
                         │  logs/YYYY-MM-DD.jsonl        │
                         └───────────────────────────────┘
```

**Two-Container Architecture:**
- `omnimcp-backend`: Python FastAPI (all APIs)
- `omnimcp-admin`: React + nginx (Admin UI)

All three transports share the same tool registry — **define once, use everywhere**.

## Key Files & Directories

### Core Application
| File | Purpose |
|------|---------|
| `app/registry.py` | Central tool registry (DO NOT BREAK!) |
| `app/loader.py` | Loads tools from `omnimcp_data/tools/` |
| `app/reload.py` | Hot reload functionality |
| `app/auth.py` | Bearer token authentication |
| `app/transports/` | OpenAPI and MCP transport implementations |
| `app/web/` | Backend API server and routes |
| `app/external/` | External MCP server integration |
| `main.py` | Server entrypoint |

### Tests
| Directory | Purpose |
|-----------|---------|
| `tests/unit/` | Unit tests (~200 tests) |
| `tests/integration/` | Integration tests (~200 tests) |
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
| `OPENAPI_PORT` | `8006` | OpenAPI server port |
| `MCP_PORT` | `8007` | MCP HTTP server port |
| `WEB_PORT` | `8080` | Backend API server port |
| `ADMIN_PORT` | `3000` | Admin UI port (nginx) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `DATA_DIR` | `omnimcp_data` | Data directory path |
| `LOG_RETENTION_DAYS` | `30` | Days to keep log files |

## Testing

```bash
# Run all tests (420+ tests)
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/test_registry.py -v
```

## Docker Commands

```bash
# Build and start
docker compose up -d --build

# View logs
docker compose logs -f

# Rebuild specific container
docker compose build omnimcp-admin
docker compose up -d omnimcp-admin

# Stop all
docker compose down
```

## Key Features

### Hot Reload
```bash
curl -X POST http://localhost:8080/api/reload \
  -H "Authorization: Bearer change_me"
```

### Playground (Admin UI)
- Test tools with Direct or MCP transport
- JSON input editor with syntax highlighting
- Real-time execution results

### Persistent Logging
- Daily log files: `DATA_DIR/logs/YYYY-MM-DD.jsonl`
- Auto-cleanup after `LOG_RETENTION_DAYS`
- In-memory buffer for live viewing

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
