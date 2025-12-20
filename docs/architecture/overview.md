# Architecture Overview

The MCP Tool Server provides a structured way to expose Python tools as machine-callable capabilities.
It separates tool logic from transport and protocol concerns.

Core principles:
- Tool contracts are defined in code
- OpenAPI is the source of truth for discovery
- MCP is an optional transport adapter
