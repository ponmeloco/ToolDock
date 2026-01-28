# External MCP Server Integration

Access 500+ community tools from the [MCP Registry](https://registry.modelcontextprotocol.io) with minimal configuration.

## Overview

OmniMCP can connect to external MCP servers and expose their tools alongside your native tools. External tools are:

- **Namespaced**: Prefixed with server ID (e.g., `github:create_repository`)
- **Discoverable**: Listed in both OpenAPI and MCP transports
- **Configurable**: Via YAML config or Admin API
- **Isolated**: Run as separate processes

## Architecture

```
┌────────────────────────────────────────────────────┐
│             Enhanced Tool Registry                  │
│  ┌──────────────┐        ┌──────────────────────┐ │
│  │ Native Tools │        │ External MCP Servers │ │
│  │ (Python)     │        │ (Proxied)            │ │
│  │              │        │                      │ │
│  │ tools/       │        │ - github (12 tools)  │ │
│  │  shared/*.py │        │ - filesystem (5)     │ │
│  │              │        │ - ...                │ │
│  └──────────────┘        └──────────────────────┘ │
└──────────────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    │               │               │
    ▼               ▼               ▼
OpenAPI         MCP HTTP        Admin API
:8006           :8007           :8006/admin
```

## Quick Links

- [Quick Start Guide](./QUICKSTART.md) - Get started in 5 minutes
- [Configuration Reference](./CONFIGURATION.md) - Full YAML options
- [Registry Guide](./REGISTRY.md) - Using the MCP Registry
- [Development Guide](./DEVELOPMENT.md) - Architecture deep-dive

## Security Considerations

- External servers run as subprocesses with STDIO transport
- Environment variables can contain secrets (use `${VAR}` syntax)
- Admin API requires Bearer token authentication
- Each server is isolated in its own process
