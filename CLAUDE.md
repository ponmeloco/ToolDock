# MCP Server Base - Claude Code Instructions

## Project Overview

This is a **Universal Tool Server** that exposes tools via both OpenAPI (REST) and MCP (Model Context Protocol) transports. The core principle: **Tools are code-defined capabilities, not prompt-based logic.**

## Current Architecture

```
┌─────────────────────────────────────┐
│      Tool Registry (Central)        │
│   tools/shared/*.py → Registry      │
└────────────┬────────────────────────┘
             │
    ┌────────▼─────────┐
    │   Dual Transport │
    │                  │
    │ OpenAPI (8006)   │  → OpenWebUI, REST clients
    │ MCP HTTP (8007)  │  → Claude Desktop, n8n
    └──────────────────┘
```

## Key Files & Directories

### Core Application
- `app/registry.py` - **Central tool registry** (DO NOT BREAK!)
- `app/loader.py` - Loads tools from `tools/shared/`
- `app/transports/` - Transport implementations
- `main.py` - Server entrypoint with mode selection

### Tools
- `tools/shared/*.py` - **Native tool definitions** (DO NOT MODIFY structure!)
  - Each tool: Pydantic schema + async handler + registration
  - Template: `tool_template.py`

### Documentation
- `README.md` - User-facing overview
- `ARCHITECTURE.md` - System design
- `LLM_INSTRUCTIONS.md` - Behavioral rules for LLMs

## Code Conventions

### Tool Definition Pattern (SACRED!)
```python
# Every tool follows this pattern:

from pydantic import BaseModel, Field

class ToolInput(BaseModel):
    """Input schema with strict validation"""
    field: str = Field(..., description="...")
    
    class Config:
        extra = "forbid"  # ← CRITICAL! Rejects unexpected fields

async def handler(input: ToolInput) -> dict:
    """Async handler - must be async!"""
    return {"result": "..."}

def register_tools(registry):
    """Registration function"""
    registry.register_tool(
        name="tool_name",
        description="Clear description",
        input_schema=ToolInput,
        handler=handler
    )
```

### Style Guidelines
- **Type hints everywhere** - `def func(arg: str) -> dict:`
- **Async for I/O** - All handlers, all external calls
- **Pydantic validation** - Never manual dict parsing
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
from pydantic import BaseModel

# 3. Local
from app.registry import registry
from app.loader import load_tools
```

## Environment & Deployment

### Docker Setup
```bash
# Build
docker compose build

# Start OpenAPI only
SERVER_MODE=openapi docker compose up tool-server-openapi

# Start MCP only
SERVER_MODE=mcp-http docker compose up tool-server-mcp-http

# Start both
SERVER_MODE=both docker compose up
```

### Environment Variables
- `SERVER_MODE` - openapi | mcp-http | both
- `BEARER_TOKEN` - API authentication
- `OPENAPI_PORT` - Default 8006
- `MCP_PORT` - Default 8007

## Testing Commands

### Health Check
```bash
curl http://localhost:8006/health
```

### List Tools
```bash
curl http://localhost:8006/tools \
  -H "Authorization: Bearer change_me"
```

### Execute Tool
```bash
curl -X POST http://localhost:8006/tools/tool_name \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"field": "value"}'
```

## Current Task: External MCP Integration

You're implementing the ability to integrate external MCP servers from the official registry.

### What Already Exists
- ✅ Dual-transport architecture
- ✅ Native tool system
- ✅ Tool registry pattern
- ✅ Docker deployment

### What You're Adding
- 🔨 MCP Registry client
- 🔨 External server proxy
- 🔨 Config-based loading
- 🔨 Admin API
- 🔨 Comprehensive docs

### Critical Constraints

#### DO NOT BREAK
- Native tool structure in `tools/shared/`
- Existing tool registration in `app/registry.py`
- OpenAPI endpoints (backward compatibility)
- Docker deployment flow

#### MUST PRESERVE
- Type safety (Pydantic validation)
- Async handlers
- Bearer token auth
- Tool naming: native vs external distinction

#### MUST ADD
- Tool namespacing: `server_id:tool_name` for external
- Process isolation for external servers
- Graceful shutdown handling
- Error logging (not just raising)

## Architecture Patterns to Follow

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

### ❌ Breaking Changes
- Don't change existing tool names
- Don't modify `ToolRegistry` API used by native tools
- Don't require config for native tools

### ❌ Security Issues
- Never commit secrets/tokens
- Always validate external inputs
- Don't use `eval()` or `exec()`
- Prefix external tools to avoid injection

### ❌ Performance Issues
- Don't block event loop (use async!)
- Don't load all external servers on every request
- Cache when possible (but invalidate correctly)

### ❌ Bad Practices
- Don't use `print()` - use `logger`
- Don't use bare `except:` - catch specific errors
- Don't ignore errors silently
- Don't hardcode paths/URLs

## Git Workflow

### Branch Naming
- Feature: `feature/external-mcp-integration`
- Fix: `fix/description`
- Docs: `docs/description`

### Commit Messages
```
feat: Add external MCP server integration

- Component 1
- Component 2

Breaking changes: None
```

### Before Committing
1. Test manually (curl commands)
2. Check logs for errors
3. Verify Docker build
4. Review diff (`git diff`)
5. No debug code left

## Documentation Standards

### User-Facing Docs
- **Audience**: Non-technical users
- **Tone**: Friendly, clear, example-heavy
- **Structure**: Quick start → Details → Advanced
- **Examples**: Real, working code snippets

### Developer Docs
- **Audience**: Contributors, maintainers
- **Tone**: Technical, precise
- **Structure**: Architecture → Implementation → Debugging
- **Diagrams**: Use ASCII art or mermaid

### API Docs
- **Format**: Endpoint, method, params, response, example
- **Completeness**: All fields documented
- **Errors**: All error codes explained

## Dependencies

### Current Stack
- **Python**: 3.11+
- **FastAPI**: 0.115.0 - Web framework
- **Pydantic**: 2.9.0 - Validation
- **uvicorn**: 0.32.0 - ASGI server
- **mcp**: 1.1.0 - MCP SDK (NEW for your work!)

### Adding Dependencies
1. Add to `requirements.txt`
2. Document why it's needed
3. Check for version conflicts
4. Test Docker build

## Debugging Tips

### Check Logs
```bash
docker compose logs -f tool-server-openapi
```

### Interactive Shell
```bash
docker compose exec tool-server-openapi bash
python
>>> from app.registry import registry
>>> registry.list_tools()
```

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Resources

### External References
- **MCP Registry**: https://registry.modelcontextprotocol.io
- **MCP Spec**: https://modelcontextprotocol.io/specification
- **MCP Python SDK**: https://github.com/modelcontextprotocol/python-sdk
- **FastAPI Docs**: https://fastapi.tiangolo.com

### Internal References
- Check `docs/` for detailed guides
- Check `tool_template.py` for tool pattern
- Check `LLM_INSTRUCTIONS.md` for behavioral rules

## Questions to Ask Yourself

Before implementing:
- ✅ Is this backward compatible?
- ✅ Does it follow existing patterns?
- ✅ Is error handling comprehensive?
- ✅ Are types annotated?
- ✅ Is it async where needed?
- ✅ Will it work in Docker?
- ✅ Is it documented?
- ✅ Can I test it easily?

## Success Metrics

Your implementation is successful if:
1. ✅ Existing native tools still work
2. ✅ External servers can be added via config
3. ✅ External tools appear in both transports
4. ✅ Documentation is complete and clear
5. ✅ No errors in logs during normal operation
6. ✅ Graceful shutdown works
7. ✅ Code is maintainable (types, docs, structure)

## Final Notes

- **Think before coding** - Plan the architecture
- **Follow patterns** - Don't reinvent wheels
- **Test incrementally** - Don't write everything then test
- **Document as you go** - Not at the end
- **Ask questions** - Better than wrong assumptions
- **Have fun!** - This is cool technology 🚀

---

Good luck! You've got this! 💪
