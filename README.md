<p align="center">
  <h1 align="center">OmniMCP</h1>
  <p align="center">
    <strong>One Server. Every Protocol. All Your Tools.</strong>
  </p>
  <p align="center">
    A dual-transport tool server exposing Python tools via <b>OpenAPI</b> and <b>MCP</b> simultaneously.
  </p>
</p>

<p align="center">
  <a href="#-quickstart"><img src="https://img.shields.io/badge/Quick-Start-blue?style=for-the-badge" alt="Quickstart"></a>
  <a href="#-features"><img src="https://img.shields.io/badge/Features-green?style=for-the-badge" alt="Features"></a>
  <a href="#-documentation"><img src="https://img.shields.io/badge/Docs-orange?style=for-the-badge" alt="Documentation"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/MCP-Streamable_HTTP-purple.svg" alt="MCP Streamable HTTP">
  <img src="https://img.shields.io/badge/OpenAPI-3.0-green.svg" alt="OpenAPI 3.0">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License">
</p>

---

## 📋 Table of Contents

- [Quickstart](#-quickstart)
- [Features](#-features)
- [Architecture](#-architecture)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Connecting Clients](#-connecting-clients)
- [Adding Tools](#-adding-tools)
- [API Reference](#-api-reference)
- [Documentation](#-documentation)
- [Contributing](#-contributing)

---

## 🚀 Quickstart

**With Docker (recommended):**

```bash
# Clone the repo
git clone https://github.com/ponmeloco/OmniMCP.git
cd OmniMCP

# Start both servers
docker compose up tool-server-openapi tool-server-mcp-http
```

**Without Docker:**

```bash
# Install dependencies
pip install -r requirements.txt

# Start both servers
SERVER_MODE=both python main.py
```

**Verify it works:**

```bash
# OpenAPI Health
curl http://localhost:8006/health

# MCP Health
curl http://localhost:8007/health

# Or run the test script
./test_both_transports.sh
```

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔀 **Dual Transport** | OpenAPI + MCP from the same codebase |
| 🧰 **Shared Registry** | Define tools once, expose everywhere |
| 🔌 **MCP Streamable HTTP** | Modern MCP transport (JSON-RPC 2.0) |
| 🌐 **OpenAPI/REST** | Full OpenAPI 3.0 spec generation |
| 🐳 **Docker Ready** | Production-ready containers |
| 🔐 **Auth Built-in** | Bearer token authentication |
| ⚡ **Hot Reload** | Add tools without server restart |

---

## 🏗 Architecture

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

Both transports share the same tool registry — **define once, use everywhere**.

---

## 📦 Installation

### Prerequisites

- Python 3.11+ or Docker
- (Optional) `jq` for pretty JSON output in tests

### Docker Installation

```bash
docker compose up tool-server-openapi tool-server-mcp-http
```

### Manual Installation

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_MODE` | `openapi` | `openapi`, `mcp-http`, or `both` |
| `TOOLS_DIR` | `./tools` | Directory containing tool modules |
| `BEARER_TOKEN` | - | Auth token for OpenAPI endpoints |
| `OPENAPI_PORT` | `8006` | Port for OpenAPI server |
| `MCP_PORT` | `8007` | Port for MCP server |
| `HOST` | `0.0.0.0` | Bind address |

### Server Modes

```bash
# OpenAPI only (for OpenWebUI)
SERVER_MODE=openapi python main.py

# MCP only (for Claude Desktop, n8n)
SERVER_MODE=mcp-http python main.py

# Both servers in parallel
SERVER_MODE=both python main.py
```

---

## 🔌 Connecting Clients

### OpenWebUI

1. Go to **Settings → Connections → OpenAPI**
2. Add URL: `http://localhost:8006`
3. Add Bearer token from your `.env`

### Claude Desktop

Add to your config (`~/.config/Claude/claude_desktop_config.json` on Linux):

```json
{
  "mcpServers": {
    "omnimcp": {
      "url": "http://localhost:8007/mcp",
      "transport": "http"
    }
  }
}
```

### n8n

Use the **MCP Node** with:
- URL: `http://localhost:8007/mcp`
- Transport: HTTP

---

## 🛠 Adding Tools

Create a new file in `tools/shared/`:

```python
# tools/shared/my_tool.py
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

Restart the server and your tool is available on both transports!

See [how-to-add-a-tool-with-a-llm.md](how-to-add-a-tool-with-a-llm.md) for LLM-assisted tool generation.

---

## 📡 API Reference

### OpenAPI Server (Port 8006)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/openapi.json` | GET | No | OpenAPI specification |
| `/tools` | GET | Yes | List all tools |
| `/tools/{name}` | POST | Yes | Execute a tool |

### MCP Server (Port 8007)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/mcp` | GET | Server info |
| `/mcp` | POST | JSON-RPC 2.0 endpoint |

**MCP Methods:**

| Method | Description |
|--------|-------------|
| `initialize` | Initialize MCP session |
| `tools/list` | List available tools |
| `tools/call` | Execute a tool |
| `ping` | Keep-alive ping |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture details |
| [LLM_INSTRUCTIONS.md](LLM_INSTRUCTIONS.md) | Instructions for LLM tool usage |
| [how-to-add-a-tool-with-a-llm.md](how-to-add-a-tool-with-a-llm.md) | Generate tools with AI |
| [tools/tool_template.py](tools/tool_template.py) | Template for new tools |

---

## 📁 Project Structure

```
OmniMCP/
├── app/
│   ├── transports/
│   │   ├── openapi_server.py    # OpenAPI transport
│   │   └── mcp_http_server.py   # MCP transport
│   ├── auth.py                  # Authentication
│   ├── errors.py                # Error types
│   ├── loader.py                # Tool loading
│   └── registry.py              # Shared registry
├── tools/
│   ├── shared/                  # Your tools here
│   │   └── example.py
│   └── tool_template.py
├── main.py                      # Entrypoint
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Make your changes
4. Test with `./test_both_transports.sh`
5. Commit (`git commit -m 'Add amazing feature'`)
6. Push (`git push origin feature/amazing`)
7. Open a Pull Request

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

<p align="center">
  <sub>Built with ❤️ for the MCP ecosystem</sub>
</p>
