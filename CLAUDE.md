# OmniMCP - Claude Code Instructions

## Project Overview

**OmniMCP** is a multi-tenant MCP server with namespace-based routing, exposing Python tools via **OpenAPI**, **MCP**, and **Web GUI**. The core principle: **Tools are code-defined capabilities, not prompt-based logic.**

## Current Architecture

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
                         └───────────────────────────────┘
```

**Two-Container Architecture:**
- `omnimcp-backend`: Python FastAPI (all APIs)
- `omnimcp-admin`: React + nginx (Admin UI)

All three transports share the same tool registry — **define once, use everywhere**.

## Key Files & Directories

### Core Application
- `app/registry.py` - **Central tool registry** (DO NOT BREAK!)
- `app/loader.py` - Loads tools from `omnimcp_data/tools/`
- `app/reload.py` - Hot reload functionality
- `app/middleware.py` - Custom middleware (trailing newlines)
- `app/auth.py` - Authentication (Bearer token)
- `app/transports/` - Transport implementations
- `app/web/` - Web GUI server and routes
- `app/external/` - External MCP server integration
- `main.py` - Server entrypoint with mode selection

### Tools
- `omnimcp_data/tools/{namespace}/*.py` - **Native tool definitions**
  - Each tool: Pydantic schema + async handler + registration
  - Each folder becomes a separate MCP namespace

### Tests
- `tests/unit/` - Unit tests for core components
- `tests/integration/` - Integration tests for endpoints
- `tests/fixtures/` - Sample tools for testing
- `conftest.py` - Shared pytest fixtures

### Documentation
- `README.md` - User-facing overview
- `ARCHITECTURE.md` - System design
- `LLM_INSTRUCTIONS.md` - Behavioral rules for LLMs

## Code Conventions

### Tool Definition Pattern (SACRED!)
```python
# Every tool follows this pattern:

from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class ToolInput(BaseModel):
    """Input schema with strict validation"""
    model_config = ConfigDict(extra="forbid")  # ← CRITICAL! Rejects unexpected fields

    field: str = Field(..., description="...")

async def handler(payload: ToolInput) -> dict:
    """Async handler - must be async!"""
    return {"result": "..."}

def register_tools(registry: ToolRegistry) -> None:
    """Registration function - called by loader"""
    ToolInput.model_rebuild(force=True)  # ← Required for hot reload

    registry.register(
        ToolDefinition(
            name="tool_name",
            description="Clear description",
            input_model=ToolInput,
            handler=handler,
        )
    )
```

### Style Guidelines
- **Type hints everywhere** - `def func(arg: str) -> dict:`
- **Async for I/O** - All handlers, all external calls
- **Pydantic validation** - Never manual dict parsing
- **ConfigDict** - Use `model_config = ConfigDict(...)` not `class Config:`
- **Descriptive names** - `create_github_repository` not `create_repo`
- **Docstrings** - Classes and non-trivial functions
- **Logging** - Use `logger.info/error/debug`, not `print()`

### Import Order
```python
# 1. Standard library
import asyncio
import os

# 2. Third-party
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

# 3. Local
from app.registry import ToolRegistry, ToolDefinition
from app.loader import load_tools_from_directory
```

## Environment & Deployment

### Docker Setup
```bash
# Build
docker compose build

# Start all services (default)
docker compose up -d

# Or use SERVER_MODE
SERVER_MODE=all docker compose up -d      # All 3 servers
SERVER_MODE=both docker compose up -d     # OpenAPI + MCP only
SERVER_MODE=openapi docker compose up -d  # OpenAPI only
SERVER_MODE=mcp-http docker compose up -d # MCP only
SERVER_MODE=web-gui docker compose up -d  # Web GUI only
```

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_MODE` | `all` | openapi, mcp-http, web-gui, both, all |
| `BEARER_TOKEN` | (required) | API authentication token |
| `OPENAPI_PORT` | `8006` | OpenAPI server port |
| `MCP_PORT` | `8007` | MCP HTTP server port |
| `WEB_PORT` | `8080` | Backend API server port |
| `ADMIN_PORT` | `3000` | Admin UI port (nginx) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `DATA_DIR` | `omnimcp_data` | Data directory path |

## Testing

### Pytest (Recommended)
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Run all tests
pytest tests/ -v

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests only
pytest tests/integration/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

### Manual Testing
```bash
# Health checks
curl http://localhost:8006/health   # OpenAPI
curl http://localhost:8007/health   # MCP
curl http://localhost:8080/health   # Web GUI

# List tools (OpenAPI)
curl http://localhost:8006/tools \
  -H "Authorization: Bearer change_me"

# List namespaces (MCP)
curl http://localhost:8007/mcp/namespaces \
  -H "Authorization: Bearer change_me"

# Execute tool
curl -X POST http://localhost:8006/tools/tool_name \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"field": "value"}'

# Hot reload all namespaces
curl -X POST http://localhost:8080/api/reload \
  -H "Authorization: Bearer change_me"
```

## Features

### Multi-Tenant Namespaces
Each folder in `omnimcp_data/tools/` becomes a separate MCP endpoint:
- `tools/shared/` → `/mcp/shared`
- `tools/team1/` → `/mcp/team1`
- `tools/finance/` → `/mcp/finance`

### Hot Reload
Reload tools at runtime without server restart:
```bash
# Reload all namespaces
curl -X POST http://localhost:8080/api/reload \
  -H "Authorization: Bearer change_me"

# Reload specific namespace
curl -X POST http://localhost:8080/api/reload/shared \
  -H "Authorization: Bearer change_me"
```

**Note:** When running in multi-process mode (`SERVER_MODE=all`), reload requests are automatically forwarded from the Web GUI to the OpenAPI server to keep all registries in sync.

### Admin UI Features
- **Dashboard**: Overview of namespaces, tools, and system health
- **Tools**: Browse namespaces, create/edit/delete tools with syntax highlighting
- **Playground**: Test tools interactively with JSON input/output
- **Logs**: View HTTP requests with colored status codes, filter by level/logger

### Create Tools from Template
Create new tools via API or Admin UI:
```bash
# Create tool from template (auto-generates boilerplate)
curl -X POST "http://localhost:8080/api/folders/shared/tools/create-from-template" \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"name": "my_new_tool"}'
```

Or use the Admin UI: **Tools** → **New Tool** button.

### External MCP Servers
Integrate tools from MCP Registry via `omnimcp_data/external/config.yaml`:
```yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
```

## Architecture Patterns

### Separation of Concerns
```
Transport Layer ← (should not know) → Tool Implementation
Config Layer ← (should not know) → Execution Logic
Registry ← (coordinates) → All Components
```

### Error Handling Pattern
```python
try:
    result = await some_operation()
    logger.info(f"Success: {result}")
    return result
except SpecificError as e:
    logger.error(f"Specific error: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise RuntimeError(f"Operation failed: {e}")
```

### Async Pattern
```python
# Good
async def external_operation():
    async with httpx.AsyncClient() as client:
        response = await client.get(...)
    return response

# Bad
def blocking_operation():
    response = requests.get(...)  # Blocks event loop!
    return response
```

## Common Pitfalls to Avoid

### Breaking Changes
- Don't change existing tool names
- Don't modify `ToolRegistry` API used by native tools
- Don't require config for native tools

### Security Issues
- Never commit secrets/tokens
- Always validate external inputs
- Prefix external tools to avoid injection

### Performance Issues
- Don't block event loop (use async!)
- Don't load all external servers on every request
- Cache when possible (but invalidate correctly)

### Bad Practices
- Don't use `print()` - use `logger`
- Don't use bare `except:` - catch specific errors
- Don't ignore errors silently
- Don't hardcode paths/URLs
- Don't use `class Config:` - use `model_config = ConfigDict(...)`

## Git Workflow

### Branch Naming
- Feature: `feature/description`
- Fix: `fix/description`
- Docs: `docs/description`

### Commit Messages
```
feat: Add hot reload functionality

- ToolReloader class with namespace support
- API endpoints for reload
- Module cache clearing

Breaking changes: None
```

### Before Committing
1. Run `pytest tests/ -v`
2. Test manually (curl commands)
3. Check logs for errors
4. Verify Docker build
5. Review diff (`git diff`)
6. No debug code left

## Dependencies

### Current Stack
- **Python**: 3.12+
- **FastAPI**: 0.115.0 - Web framework
- **Pydantic**: 2.9.0 - Validation
- **uvicorn**: 0.32.0 - ASGI server
- **mcp**: 1.1.0+ - MCP SDK
- **httpx**: 0.28.0 - Async HTTP client

### Test Dependencies
- **pytest**: 8.0.0+ - Test framework
- **pytest-asyncio**: 0.23.0+ - Async test support
- **pytest-cov**: 4.1.0+ - Coverage reporting

### Adding Dependencies
1. Add to `requirements.txt`
2. Document why it's needed
3. Check for version conflicts
4. Test Docker build

## Debugging Tips

### Check Logs
```bash
docker compose logs -f
```

### Interactive Shell
```bash
docker compose exec omnimcp bash
python
>>> from app.registry import ToolRegistry
>>> registry = ToolRegistry()
>>> registry.list_tools()
```

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Project Structure

```
OmniMCP/
├── admin-ui/                    # React Admin Frontend (separate container)
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── pages/               # Dashboard, Tools, Playground, Logs
│   │   └── api/                 # API client
│   ├── Dockerfile               # Nginx-based production build
│   ├── nginx.conf               # Nginx config with security headers
│   └── package.json
├── app/
│   ├── transports/
│   │   ├── openapi_server.py    # OpenAPI transport
│   │   └── mcp_http_server.py   # MCP transport
│   ├── web/
│   │   ├── server.py            # Backend API server
│   │   ├── validation.py        # Tool validation
│   │   └── routes/              # API routes (folders, tools, reload, admin)
│   ├── external/
│   │   ├── server_manager.py    # External server management
│   │   └── config.py            # Config loading
│   ├── admin/
│   │   └── routes.py            # OpenAPI admin routes (external servers)
│   ├── auth.py                  # Authentication (Bearer token)
│   ├── loader.py                # Tool loading
│   ├── reload.py                # Hot reload
│   ├── middleware.py            # Custom middleware
│   ├── errors.py                # Custom exceptions
│   └── registry.py              # Shared registry
├── tests/
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests
│   └── fixtures/                # Test fixtures
├── omnimcp_data/                # Data volume
│   ├── tools/                   # Tool namespaces
│   │   ├── tool_template.py     # Template for new tools
│   │   └── shared/              # Default namespace
│   └── external/config.yaml     # External server config
├── main.py                      # Backend entrypoint
├── start.sh                     # Startup script
├── pytest.ini                   # Pytest config
├── docker-compose.yml           # Two-container setup
├── Dockerfile                   # Backend container
├── .env                         # Configuration
└── requirements.txt
```

## Resources

### External References
- **MCP Registry**: https://registry.modelcontextprotocol.io
- **MCP Spec**: https://modelcontextprotocol.io/specification
- **MCP Python SDK**: https://github.com/modelcontextprotocol/python-sdk
- **FastAPI Docs**: https://fastapi.tiangolo.com

### Internal References
- Check `docs/` for detailed guides
- Check `LLM_INSTRUCTIONS.md` for behavioral rules
- Check existing tools in `omnimcp_data/tools/shared/` for patterns

## Questions to Ask Yourself

Before implementing:
- Does it follow existing patterns?
- Is error handling comprehensive?
- Are types annotated?
- Is it async where needed?
- Will it work in Docker?
- Is it documented?
- Do tests pass?
