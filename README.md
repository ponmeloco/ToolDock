<p align="center">
  <h1 align="center">OmniMCP</h1>
  <p align="center">
    <strong>One Server. Every Protocol. All Your Tools.</strong>
  </p>
  <p align="center">
    Multi-tenant MCP server with namespace-based routing, exposing Python tools via <b>OpenAPI</b>, <b>MCP</b>, and <b>Web GUI</b>.
  </p>
</p>

<p align="center">
  <a href="#-quickstart"><img src="https://img.shields.io/badge/Quick-Start-blue?style=for-the-badge" alt="Quickstart"></a>
  <a href="#-features"><img src="https://img.shields.io/badge/Features-green?style=for-the-badge" alt="Features"></a>
  <a href="#-documentation"><img src="https://img.shields.io/badge/Docs-orange?style=for-the-badge" alt="Documentation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/MCP-Streamable_HTTP-purple.svg" alt="MCP Streamable HTTP">
  <img src="https://img.shields.io/badge/OpenAPI-3.0-green.svg" alt="OpenAPI 3.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License">
</p>

---

## Table of Contents

- [Quickstart](#-quickstart)
- [Features](#-features)
- [Architecture](#-architecture)
- [Configuration](#-configuration)
- [Namespace Routing](#-namespace-routing)
- [Connecting Clients](#-connecting-clients)
- [Adding Tools](#-adding-tools)
- [API Reference](#-api-reference)
- [Documentation](#-documentation)

---

## Quickstart

**With Docker (recommended):**

```bash
# Clone the repo
git clone https://github.com/ponmeloco/OmniMCP.git
cd OmniMCP

# Quick start (creates .env, builds, starts, runs tests)
chmod +x start.sh
./start.sh
```

**Or manual setup:**

```bash
# Configure (change BEARER_TOKEN!)
cp .env.example .env
nano .env

# Start all services
docker compose up -d

# Check logs
docker compose logs -f
```

**Verify it works:**

```bash
# Health checks
curl http://localhost:8006/health   # OpenAPI
curl http://localhost:8007/health   # MCP HTTP
curl http://localhost:8080/health   # Backend API
curl http://localhost:3000          # Admin UI
```

**Access Admin UI:**

Open http://localhost:3000 in your browser.
Enter your `BEARER_TOKEN` from `.env` when prompted.

---

## Features

| Feature | Description |
|---------|-------------|
| **Admin UI** | React-based dashboard with code editor, tool playground, and log viewer |
| **Multi-Tenant Namespaces** | Organize tools in folders, each becomes a separate MCP endpoint |
| **Dual Transport** | OpenAPI + MCP from the same codebase |
| **Namespace Routing** | `/mcp/shared`, `/mcp/team1`, `/mcp/github` - separate endpoints per namespace |
| **External MCP Servers** | Integrate tools from MCP Registry (GitHub, MSSQL, Filesystem, etc.) |
| **Hot Reload** | Reload tools at runtime without server restart |
| **Tool Playground** | Test tools directly in the browser with JSON input/output |
| **Code Editor** | Edit Python tools with syntax highlighting (CodeMirror) |
| **Docker Ready** | Multi-container setup with configurable ports |
| **Auth Built-in** | Bearer token authentication |
| **Tool Validation** | AST-based validation for uploaded tools |

---

## Architecture

```
┌──────────────────┐     ┌─────────────────────────────────────┐
│   Admin UI       │     │         OmniMCP Backend             │
│   (React)        │     ├─────────────────────────────────────┤
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

All transports share the same tool registry — **define once, use everywhere**.

---

## Configuration

### Environment Variables (.env)

```bash
# Required
BEARER_TOKEN=your_secure_token_here

# Optional - Ports (defaults shown)
#OPENAPI_PORT=8006
#MCP_PORT=8007
#WEB_PORT=8080
#ADMIN_PORT=3000

# Optional - Security
#CORS_ORIGINS=https://myapp.example.com

# Optional - External MCP Servers
#GITHUB_TOKEN=ghp_xxxxxxxxxxxx
#MSSQL_CONNECTION_STRING=Server=localhost;Database=mydb;...
```

### Server Modes

```bash
# All services in one container (default)
SERVER_MODE=all docker compose up -d

# Or start specific modes
SERVER_MODE=both python main.py      # OpenAPI + MCP only
SERVER_MODE=web-gui python main.py   # Web GUI only
SERVER_MODE=openapi python main.py   # OpenAPI only
SERVER_MODE=mcp-http python main.py  # MCP only
```

### Data Directory Structure

```
omnimcp_data/
├── tools/
│   ├── tool_template.py  # Template for new tools
│   ├── shared/           # Default namespace
│   │   └── example.py
│   └── {namespace}/      # Add more namespaces as folders
│       └── *.py
├── external/
│   └── config.yaml       # External MCP server config
└── config/
    └── settings.yaml     # Global settings
```

---

## Namespace Routing

Each folder in `omnimcp_data/tools/` becomes a separate MCP namespace:

| Folder | MCP Endpoint | Use Case |
|--------|--------------|----------|
| `tools/shared/` | `/mcp/shared` | Default tools for everyone |
| `tools/team1/` | `/mcp/team1` | Team 1 specific tools |
| `tools/finance/` | `/mcp/finance` | Finance department tools |

**LiteLLM Configuration:**

```yaml
mcp_servers:
  - server_name: "shared"
    url: "http://omnimcp:8007/mcp/shared"
    api_key_header: "Authorization"
    api_key_value: "Bearer ${OMNIMCP_TOKEN}"

  - server_name: "team1"
    url: "http://omnimcp:8007/mcp/team1"
    api_key_header: "Authorization"
    api_key_value: "Bearer ${OMNIMCP_TOKEN}"
```

**List all namespaces:**

```bash
curl http://localhost:8007/mcp/namespaces \
  -H "Authorization: Bearer change_me"
```

---

## External MCP Server Integration

Add external servers from the MCP Registry in `omnimcp_data/external/config.yaml`:

```yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}

  mssql:
    source: custom
    enabled: true
    command: npx
    args:
      - "-y"
      - "@anthropic/mcp-server-mssql"
    env:
      MSSQL_CONNECTION_STRING: ${MSSQL_CONNECTION_STRING}
```

Each external server becomes its own namespace:
- `/mcp/github` → GitHub tools
- `/mcp/mssql` → MSSQL tools

---

## Connecting Clients

### LiteLLM

```yaml
# litellm_config.yaml
mcp_servers:
  - server_name: "omnimcp-shared"
    url: "http://localhost:8007/mcp/shared"
    api_key_header: "Authorization"
    api_key_value: "Bearer change_me"
```

### Claude Desktop

Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "omnimcp": {
      "url": "http://localhost:8007/mcp/shared",
      "headers": {
        "Authorization": "Bearer change_me"
      }
    }
  }
}
```

### OpenWebUI

1. Go to **Settings → Connections → OpenAPI**
2. Add URL: `http://localhost:8006`
3. Add Bearer token from your `.env`

### n8n

Use the **MCP Node** with:
- URL: `http://localhost:8007/mcp/shared`
- Transport: HTTP

---

## Adding Tools

Create a new file in `omnimcp_data/tools/shared/`:

```python
# omnimcp_data/tools/shared/my_tool.py
from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class MyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="The query to process")

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

Restart the server and your tool is available!

**Or upload via Web GUI API:**

```bash
curl -X POST "http://localhost:8080/api/folders/shared/tools" \
  -H "Authorization: Bearer change_me" \
  -F "file=@my_tool.py"
```

---

## API Reference

### OpenAPI Server (Port 8006)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/openapi.json` | GET | No | OpenAPI specification |
| `/tools` | GET | Yes | List all tools |
| `/tools/{name}` | POST | Yes | Execute a tool |

### MCP Server (Port 8007)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/mcp/namespaces` | GET | Yes | List all namespaces |
| `/mcp/{namespace}` | GET | Yes | Namespace info |
| `/mcp/{namespace}` | POST | Yes | JSON-RPC 2.0 endpoint |
| `/mcp` | POST | Yes | Global JSON-RPC (all tools) |

**MCP Methods:**

| Method | Description |
|--------|-------------|
| `initialize` | Initialize MCP session |
| `tools/list` | List available tools |
| `tools/call` | Execute a tool |
| `ping` | Keep-alive ping |

### Backend API (Port 8080)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/` | GET | No | Redirect to /docs |
| `/docs` | GET | No | OpenAPI documentation |
| `/api/dashboard` | GET | Bearer | Dashboard data |
| `/api/folders` | GET | Bearer | List namespaces |
| `/api/folders/{ns}/tools` | GET | Bearer | List tools in namespace |
| `/api/folders/{ns}/tools` | POST | Bearer | Upload tool file |
| `/api/folders/{ns}/tools/{file}` | PUT | Bearer | Update tool content |
| `/api/servers` | GET | Bearer | List external servers |
| `/api/reload` | POST | Bearer | Hot reload all namespaces |
| `/api/reload/{ns}` | POST | Bearer | Hot reload specific namespace |
| `/api/reload/status` | GET | Bearer | Reload status info |
| `/api/admin/health` | GET | Bearer | System health status |
| `/api/admin/logs` | GET | Bearer | View system logs |
| `/api/admin/info` | GET | Bearer | System information |

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture details |
| [LLM_INSTRUCTIONS.md](LLM_INSTRUCTIONS.md) | Instructions for LLM tool usage |
| [how-to-add-a-tool-with-a-llm.md](how-to-add-a-tool-with-a-llm.md) | Generate tools with AI |
| [docs/external-servers/](docs/external-servers/) | External MCP server integration |

---

## Project Structure

```
OmniMCP/
├── admin-ui/                    # React Admin Frontend
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── pages/               # Dashboard, Tools, Playground, Logs
│   │   └── api/                 # API client
│   ├── Dockerfile               # Nginx-based production build
│   └── package.json
├── app/
│   ├── transports/
│   │   ├── openapi_server.py    # OpenAPI transport
│   │   └── mcp_http_server.py   # MCP transport
│   ├── web/
│   │   ├── server.py            # Backend API server
│   │   ├── validation.py        # Tool validation
│   │   └── routes/              # API routes
│   ├── external/
│   │   ├── server_manager.py    # External server management
│   │   └── config.py            # Config loading
│   ├── auth.py                  # Authentication
│   ├── loader.py                # Tool loading
│   ├── reload.py                # Hot reload
│   ├── middleware.py            # Custom middleware
│   └── registry.py              # Shared registry
├── tests/
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests
│   └── fixtures/                # Test fixtures
├── omnimcp_data/                # Data volume
│   ├── tools/                   # Tool namespaces
│   │   ├── tool_template.py     # Template
│   │   └── shared/              # Default namespace
│   └── external/config.yaml     # External servers
├── main.py                      # Backend entrypoint
├── docker-compose.yml           # Multi-container setup
└── Dockerfile                   # Backend container
```

---

## Testing

### Unit & Integration Tests (pytest)

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest tests/ -v

# Run only unit tests
pytest tests/unit/ -v

# Run only integration tests
pytest tests/integration/ -v

# Run with coverage report
pytest tests/ --cov=app --cov-report=html
```

### Manual Testing

```bash
# Run bash integration tests
./test_both_transports.sh

# Test specific endpoints
curl http://localhost:8007/mcp/namespaces -H "Authorization: Bearer change_me"

curl -X POST http://localhost:8007/mcp/shared \
  -H "Authorization: Bearer change_me" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Hot reload tools (no server restart needed)
curl -X POST http://localhost:8080/api/reload \
  -H "Authorization: Bearer change_me"
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built with care for the MCP ecosystem</sub>
</p>
