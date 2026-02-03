# Configuration Reference

Complete reference for `tooldock_data/external/config.yaml` (or `$DATA_DIR/external/config.yaml`).

## File Location

```
tooldock_data/external/config.yaml
```

Override with environment variable:
```bash
EXTERNAL_CONFIG=/path/to/config.yaml
```

## Schema

```yaml
servers:
  <server_id>:
    source: registry | custom
    enabled: true | false

    # For registry source:
    name: "registry/server-name"
    env:
      VAR_NAME: value
    args:
      - additional
      - args

    # For custom STDIO source:
    type: stdio
    command: "npx"
    args: ["-y", "package-name"]
    env:
      VAR: value

    # For custom HTTP source:
    type: http
    url: "https://example.com/mcp"
    headers:
      Authorization: "Bearer token"

settings:
  auto_reload: false
  cache_schemas: true
  connection_timeout: 30
  tool_timeout: 60
```

## Server Configuration

### source: registry

Load server metadata from MCP Registry:

```yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
```

The registry provides:
- Command to run (npx/uvx/docker)
- Package identifier
- Default arguments

You can override:
- `env`: Environment variables
- `args`: Additional arguments (appended to defaults)

### source: custom (STDIO)

Run a custom command:

```yaml
servers:
  my-tool:
    source: custom
    type: stdio
    enabled: true
    command: python
    args:
      - /path/to/server.py
      - --option
      - value
    env:
      API_KEY: ${MY_API_KEY}
```

### source: custom (HTTP)

Connect to a remote MCP server:

```yaml
servers:
  remote:
    source: custom
    type: http
    enabled: true
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
```

**Note:** HTTP transport is not yet implemented.

## Environment Variables

Use `${VAR_NAME}` syntax for environment variable substitution:

```yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
      GITHUB_ORG: ${GITHUB_ORG}
```

Variables are resolved at load time from the process environment.

## Settings

### auto_reload

```yaml
settings:
  auto_reload: false
```

When `true`, automatically reload config when file changes. **Not yet implemented.**

### cache_schemas

```yaml
settings:
  cache_schemas: true
```

Cache tool schemas in `tooldock_data/external/cache/` for faster startup.

### connection_timeout

```yaml
settings:
  connection_timeout: 30
```

Timeout in seconds for establishing server connection.

### tool_timeout

```yaml
settings:
  tool_timeout: 60
```

Timeout in seconds for individual tool calls.

## Examples

### Multiple Servers

```yaml
servers:
  github:
    source: registry
    name: "modelcontextprotocol/server-github"
    enabled: true
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}

  filesystem:
    source: custom
    type: stdio
    enabled: true
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/home/user/documents"

  postgres:
    source: registry
    name: "modelcontextprotocol/server-postgres"
    enabled: false  # Disabled
    env:
      POSTGRES_CONNECTION_STRING: ${DATABASE_URL}
```

### Server with Multiple Arguments

```yaml
servers:
  filesystem:
    source: custom
    type: stdio
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/path/one"
      - "/path/two"
      - "--read-only"
```

## Validation

On startup, ToolDock validates:

1. YAML syntax is correct
2. Required fields are present (`source`, `command`/`name`)
3. Environment variables exist (warning if missing)
4. Server can be started (error logged if not)

Failed servers don't prevent startup - other servers continue loading.
