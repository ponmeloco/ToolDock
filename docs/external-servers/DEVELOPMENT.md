# Development Guide

Architecture deep-dive for contributors and advanced users.

## Component Overview

```
app/external/
├── __init__.py           # Module exports
├── registry_client.py    # MCP Registry API client
├── server_manager.py     # Server lifecycle management
├── proxy.py              # Individual server proxy
└── config.py             # YAML config management

app/admin/
├── __init__.py           # Module exports
└── routes.py             # Admin API endpoints
```

## Component Responsibilities

### MCPRegistryClient (`registry_client.py`)

Interfaces with the MCP Registry API:

```python
client = MCPRegistryClient()

# Search for servers
results = await client.search_servers("github")

# Get specific server
server = await client.get_server("modelcontextprotocol/server-github")

# Convert to internal config format
config = client.get_server_config(server)
```

### MCPServerProxy (`proxy.py`)

Manages a single external server connection:

```python
proxy = MCPServerProxy("github", config)

# Connect and discover tools
await proxy.connect()

# Execute a tool
result = await proxy.call_tool("create_repository", {"name": "test"})

# Cleanup
await proxy.disconnect()
```

Uses the MCP Python SDK:
- `StdioServerParameters` for subprocess configuration
- `stdio_client()` for transport
- `ClientSession` for protocol handling

### ExternalServerManager (`server_manager.py`)

Orchestrates multiple servers:

```python
manager = ExternalServerManager(registry)

# Add server (connects + registers tools)
await manager.add_server("github", config)

# Remove server (unregisters tools + disconnects)
await manager.remove_server("github")

# Shutdown all
await manager.shutdown_all()
```

### ExternalServerConfig (`config.py`)

Handles YAML configuration:

```python
config = ExternalServerConfig("tooldock_data/external/config.yaml")

# Load and apply to manager
await config.apply(manager)

# Add server to config file
config.add_server_to_config("github", source="registry", name="...")
```

## Data Flow

### Startup Flow

```
1. main.py: load_tools_into_registry()
   └── Loads native tools from tools/shared/

2. main.py: init_external_servers()
   ├── Creates ExternalServerManager
   ├── Creates ExternalServerConfig
   └── Calls config.apply(manager)
       └── For each enabled server:
           ├── Get config (from registry or custom)
           ├── manager.add_server()
           │   ├── Create MCPServerProxy
           │   ├── proxy.connect()
           │   │   ├── Start subprocess via stdio_client()
           │   │   ├── Initialize MCP session
           │   │   └── Discover tools via list_tools()
           │   └── Register tools in ToolRegistry
           └── Log success/failure
```

### Tool Execution Flow

```
1. Request arrives (OpenAPI or MCP transport)
   └── /tools/github:create_repository

2. ToolRegistry.call("github:create_repository", args)
   └── Detects external tool (has ":" prefix)

3. ToolRegistry._call_external_tool()
   └── Gets proxy from _external_tools dict

4. MCPServerProxy.call_tool("create_repository", args)
   └── session.call_tool() via MCP SDK

5. Result returned through layers
```

### Shutdown Flow

```
1. Signal received (SIGINT/SIGTERM)

2. main.py: shutdown_external_servers()
   └── manager.shutdown_all()
       └── For each server:
           ├── Unregister tools from registry
           ├── proxy.disconnect()
           │   └── Close session and subprocess
           └── Remove from servers dict
```

## Tool Namespacing

External tools are prefixed with server ID:

```
server_id:original_tool_name
```

Examples:
- `github:create_repository`
- `filesystem:read_file`
- `postgres:query`

This prevents conflicts between:
- External tools from different servers
- External tools and native tools

## Error Handling

### Server Connection Failures

```python
try:
    await proxy.connect()
except Exception as e:
    logger.error(f"Failed to connect: {e}")
    # Server skipped, others continue loading
```

### Tool Execution Failures

```python
try:
    result = await proxy.call_tool(name, args)
except Exception as e:
    return {
        "content": [{"type": "text", "text": f"Error: {e}"}],
        "isError": True
    }
```

## Testing

### Unit Tests

Test individual components:

```python
# Test registry client
async def test_search_servers():
    client = MCPRegistryClient()
    results = await client.search_servers("github")
    assert len(results) > 0

# Test config loading
def test_config_load():
    config = ExternalServerConfig("test_config.yaml")
    data = config.load()
    assert "servers" in data
```

### Integration Tests

Test full flow:

```bash
# Start server with test config
EXTERNAL_CONFIG=tests/external_config.yaml SERVER_MODE=both python main.py &

# Wait for startup
sleep 5

# Test tool execution
curl -X POST "http://localhost:18006/tools/test:echo" \
  -H "Authorization: Bearer test" \
  -d '{"message": "hello"}'
```

### Manual Testing

```bash
# Run the test script
./scripts/test_external_servers.sh
```

## Adding New Features

### Supporting New Transport (e.g., WebSocket)

1. Create `app/external/transports/websocket.py`
2. Implement connection/session logic
3. Update `MCPServerProxy` to detect and use new transport
4. Update `get_server_config()` to parse new transport type

### Adding Server Health Checks

1. Add `async def health_check()` to `MCPServerProxy`
2. Implement periodic ping or status check
3. Add health status to `list_servers()` response
4. Consider auto-reconnect on failure

### Implementing Schema Caching

1. Add cache directory: `tooldock_data/external/cache/`
2. On connect: Check cache before calling `list_tools()`
3. Store tool schemas as JSON files
4. Invalidate based on server version or TTL
