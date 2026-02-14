# ToolDock v2 — Final Architecture Plan

## Vision

Universal Python tool gateway. Each namespace is a self-contained tool server exposed via MCP + OpenAPI. Drop a folder into the volume and call `reload_core()` (or wait for manager watcher) to get endpoints. Core never goes down. Everything managed via tools.

---

## Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Tool framework | `fastmcp==2.14.5` (pinned) | Stable `@tool` decorator, portable tool files |
| MCP protocol target | Streamable HTTP `2025-11-25` + compatibility with `2025-06-18`, `2025-03-26`, and legacy HTTP+SSE | SOTA transport while keeping older clients working |
| Namespace routing | `X-Namespace` header | No URL parsing, no reserved prefixes, clean |
| No "all tools" | Specific namespace or 400 | Each namespace = separate server for LiteLLM/OpenWebUI |
| Execution path | OpenAPI wraps tool engine, MCP wraps tool engine | One handler, no divergence |
| Process split | Core + Manager containers | Core always alive, manager can restart/install |
| Per-ns isolation | One worker process + one virtualenv per namespace | True dependency and runtime isolation across namespaces |
| Dependency sync model | `reload_core` ensures namespace venv matches `requirements.txt` hash | Drop-in behavior stays deterministic even for new namespaces |
| Secrets | Encrypted secret payload + plaintext metadata (status only) | Secrets never traverse MCP/LLM tools, still operable by humans |
| Reload security | `/reload` requires bearer + manager token + source CIDR allowlist | Defense in depth (auth + network policy) |
| No database | Filesystem is the database | Directories = namespaces, files = tools, YAML = config |
| No monoliths | Every file < 200 lines, packages for complex domains | Readable, testable, maintainable |

---

## Architecture

```
┌──────────────────┐         ┌───────────────────────┐
│  tooldock-core   │         │  tooldock-manager      │
│  Port 8000       │         │  Port 8001             │
│                  │         │                        │
│  MCP + OpenAPI   │◄────────┤  Namespace mgmt        │
│  Session/state   │ reload  │  Venv install/build    │
│  Worker router   │ signal  │  Secrets metadata      │
│  Stream handling │         │  Human secret CLI       │
└───────┬──────────┘         └──────────┬─────────────┘
        │                                │
        │ RPC over local sockets         │
        ▼                                ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Worker: github   │   │ Worker: devops   │   │ Worker: shared   │
│ /data/venvs/...  │   │ /data/venvs/...  │   │ /data/venvs/...  │
│ Own process env  │   │ Own process env  │   │ Own process env  │
└──────────────────┘   └──────────────────┘   └──────────────────┘
             \                |                /
              \               |               /
               └──────────────▼──────────────┘
                       ┌─────────────┐
                       │   Volume    │
                       │   /data/    │
                       └─────────────┘
```

### Architecture Hardening (recommended)

- Atomic registry snapshots: build a full new namespace map, then swap pointer in one step.
- Worker health supervision: crash loop detection + exponential backoff restart.
- Per-tool execution controls: timeout, max payload size, max concurrency per namespace.
- Structured audit logs: request id, namespace, tool, latency, status, protocol version.
- Optional admission controls: namespace-level rate limits and allow/deny lists.

### Worker Runtime Contract (implementation-grade)

- Worker entrypoint:
  `python -m app.worker_main --namespace <ns> --socket /data/workers/<ns>.sock --venv /data/venvs/<ns>`
- Worker boot:
  - Activate namespace venv interpreter.
  - Import namespace tool files.
  - Build tool registry and schemas.
  - Start Unix socket server and emit `{"op":"ready","namespace":"<ns>","tools":[...]}`.
- Core to worker protocol:
  - Transport: newline-delimited JSON over Unix domain socket.
  - Request shape:
    `{"id":"req-123","op":"tools.call","tool":"list_issues","arguments":{"owner":"x","repo":"y"}}`
  - Response shape success:
    `{"id":"req-123","ok":true,"result":{...},"latency_ms":23}`
  - Response shape error:
    `{"id":"req-123","ok":false,"error":{"code":"invalid_arguments","message":"...","details":{...}}}`
- Supported ops:
  - `tools.list`
  - `tools.get_schema`
  - `tools.call`
  - `ping`
  - `shutdown`
- Standard worker error codes:
  - `tool_not_found`
  - `invalid_arguments`
  - `dependency_error`
  - `execution_timeout`
  - `internal_error`
- Core mapping:
  - OpenAPI: `tool_not_found -> 404`, `invalid_arguments -> 422`, `execution_timeout -> 504`, other -> 500.
  - MCP: returned via `tools/call` with `isError=true` and structured error content.
- Timeouts/concurrency:
  - Per-call timeout enforced in core (`TOOL_CALL_TIMEOUT_SECONDS`).
  - Per-namespace semaphore in core (`NAMESPACE_MAX_CONCURRENCY`).
  - Worker is single-threaded async event loop for deterministic execution.

---

## Volume Layout

```
/data/
├── tools/                          # One directory per namespace
│   ├── shared/                     # Default namespace
│   │   └── hello.py
│   ├── github/
│   │   ├── issues.py
│   │   ├── pulls.py
│   │   ├── requirements.txt        # Namespace pip dependencies
│   │   └── tooldock.yaml           # Namespace metadata
│   └── devops/
│       ├── deploy.py
│       └── requirements.txt
├── venvs/                          # Per-namespace virtualenvs
│   ├── github/                     # python -m venv /data/venvs/github
│   └── devops/
├── workers/                        # Unix sockets / runtime state
│   ├── github.sock
│   └── devops.sock
├── secrets.enc                     # Encrypted secret payload (values only)
├── secrets.meta.yaml               # Plaintext metadata: keys + status only
├── secrets.lock                    # File lock for atomic secret writes
├── config.yaml                     # Optional global config
├── repos/                          # Cloned repos (manager workspace)
└── logs/                           # Daily JSONL request logs
    └── 2026-02-13.jsonl
```

---

## Drop-in Namespace Convention

### Minimum viable namespace

```
my-tools/
└── hello.py          # One .py file with @tool functions
```

### Full namespace

```
github/
├── issues.py              # Tool files (any .py with @tool)
├── pulls.py
├── repos.py
├── requirements.txt       # pip dependencies
└── tooldock.yaml          # Metadata + secret declarations
```

### Tool file pattern

```python
# github/issues.py
import os
import httpx
from fastmcp.tools import tool

@tool
async def list_issues(owner: str, repo: str, state: str = "open") -> list[dict]:
    """List GitHub issues for a repository."""
    token = os.environ["GITHUB_TOKEN"]  # injected by secrets store
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/issues",
            params={"state": state},
            headers={"Authorization": f"token {token}"},
        )
        resp.raise_for_status()
        return resp.json()
```

### `tooldock.yaml`

```yaml
description: "GitHub API tools"
version: "1.0.0"
author: "someone"
secrets:
  - GITHUB_TOKEN              # Required: must exist in secrets store
env:
  GITHUB_API_URL: "https://api.github.com"  # Non-secret defaults
```

### Rules

- Directory name = namespace name (lowercase, hyphens OK)
- Any `.py` with `@tool` decorated functions = tools
- Files starting with `_` or `.` are ignored
- `__pycache__/`, `.git/` are ignored
- `requirements.txt`, `tooldock.yaml`, `README.md`, `LICENSE` are metadata, not tools
- Reserved name: `_system` (built-in management tools)

---

## Project Structure

### Core (`tooldock-core`)

```
core/
├── app/
│   ├── __init__.py
│   ├── gateway.py                  # FastAPI app, lifespan, wiring
│   ├── engine.py                   # Tool engine: list_tools(), call_tool() via workers
│   ├── auth.py                     # Bearer token middleware
│   ├── security.py                 # Internal endpoint guards (CIDR + manager token)
│   ├── secrets.py                  # Read/decrypt secret payload + metadata
│   ├── config.py                   # Settings from env vars
│   ├── worker_main.py              # Namespace worker entrypoint (socket server)
│   ├── registry/
│   │   ├── __init__.py
│   │   ├── scanner.py             # Filesystem scanning: dirs → namespaces
│   │   ├── loader.py              # Parse tool files, extract schema metadata
│   │   └── models.py             # ToolEntry, NamespaceInfo dataclasses
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── supervisor.py          # Start/stop/restart per-namespace workers
│   │   ├── rpc.py                 # Core <-> worker RPC client
│   │   └── protocol.py            # Typed request/response protocol
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── handler.py             # HTTP handler: streamable HTTP + SSE negotiation
│   │   ├── session.py             # Session + protocol version management
│   │   ├── stream.py              # SSE event buffering, resume, replay window
│   │   ├── jsonrpc.py             # JSON-RPC parsing + response building
│   │   ├── methods.py             # MCP methods: initialize, initialized, tools/list, call
│   │   └── legacy.py              # Legacy HTTP+SSE adapter (/sse + /messages)
│   └── openapi/
│       ├── __init__.py
│       └── routes.py              # REST endpoints wrapping engine
├── main.py                         # uvicorn entrypoint
├── Dockerfile
└── requirements.txt
```

### Manager (`tooldock-manager`)

```
manager/
├── app/
│   ├── __init__.py
│   ├── server.py                   # FastAPI app, MCP endpoint for _system
│   ├── config.py                   # Settings (CORE_URL, etc.)
│   ├── core_client.py             # HTTP client to signal core reload
│   ├── watcher.py                 # Optional fs watcher: tools/requirements changes -> reload_core
│   ├── cli/
│   │   ├── __init__.py
│   │   └── secrets.py             # Human-only secret set/edit commands
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── namespaces.py          # create/delete/list namespaces
│   │   ├── tool_files.py          # read/write/delete tool files
│   │   ├── dependencies.py        # venv sync, add/remove requirements
│   │   ├── secrets.py             # placeholder/list/delete/check (no values)
│   │   ├── builder.py             # analyze repo, generate tool code
│   │   ├── installer.py           # registry search, install from repo
│   │   └── introspect.py          # health, config, tool schemas
│   └── repo/
│       ├── __init__.py
│       ├── clone.py               # Git clone + analysis
│       └── analyze.py             # Detect language, tools, deps, APIs
├── main.py                         # uvicorn entrypoint
├── Dockerfile
└── requirements.txt
```

### Shared

```
tests/
├── conftest.py                     # Shared fixtures, temp dirs, test client
├── core/
│   ├── test_engine.py
│   ├── test_scanner.py
│   ├── test_loader.py
│   ├── test_worker_rpc.py
│   ├── test_secrets.py
│   ├── test_auth.py
│   ├── test_mcp_handler.py
│   ├── test_mcp_session.py
│   ├── test_mcp_jsonrpc.py
│   ├── test_mcp_methods.py
│   ├── test_openapi_routes.py
│   └── test_gateway.py
├── manager/
│   ├── test_namespaces.py
│   ├── test_tool_files.py
│   ├── test_dependencies.py
│   ├── test_secrets.py
│   ├── test_builder.py
│   └── test_installer.py
└── integration/
    ├── test_drop_in.py             # Drop folder → tools available
    ├── test_mcp_compliance.py      # Full MCP spec compliance
    ├── test_openapi_compliance.py  # OpenAPI correctness
    └── test_core_manager.py        # Manager signals core, e2e

examples/                               # NOT loaded — reference only
├── basic-tool/
│   └── hello.py                        # Minimal: one sync tool
├── async-tool/
│   ├── weather.py                      # Async tool with httpx
│   ├── requirements.txt                # Shows how to declare deps
│   └── tooldock.yaml                   # Shows metadata + secrets declaration
├── multi-tool/
│   ├── math_tools.py                   # Multiple @tool in one file
│   └── string_tools.py                 # Multiple files in one namespace
└── README.md                           # Explains the pattern with comments

docker-compose.yml
.env.example
README.md
```

### Examples Folder (reference, not loaded)

Ships with the repo so anyone can see the exact pattern. Not mounted into `/data/tools/`, purely documentation-as-code.

**`examples/basic-tool/hello.py`:**
```python
"""
Minimal ToolDock tool example.
Drop this file into tooldock_data/tools/my-namespace/ and it works.
"""
from fastmcp.tools import tool


@tool
def say_hello(name: str = "World") -> str:
    """Greet someone by name.

    Args:
        name: The person to greet. Defaults to "World".

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"
```

**`examples/async-tool/weather.py`:**
```python
"""
Async tool example with external API call.
Requires: httpx (declared in requirements.txt)
Requires: WEATHER_API_KEY secret (declared in tooldock.yaml)
"""
import os
import httpx
from fastmcp.tools import tool


@tool
async def get_weather(city: str, units: str = "metric") -> dict:
    """Get current weather for a city.

    Args:
        city: City name (e.g. "Berlin", "New York").
        units: Temperature units — "metric" (Celsius) or "imperial" (Fahrenheit).

    Returns:
        Dict with temperature, description, humidity.
    """
    api_key = os.environ["WEATHER_API_KEY"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "units": units, "appid": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "city": data["name"],
        "temperature": data["main"]["temp"],
        "description": data["weather"][0]["description"],
        "humidity": data["main"]["humidity"],
    }
```

**`examples/async-tool/requirements.txt`:**
```
httpx>=0.28.0
```

**`examples/async-tool/tooldock.yaml`:**
```yaml
description: "Weather API tools"
version: "1.0.0"
secrets:
  - WEATHER_API_KEY
env:
  WEATHER_BASE_URL: "https://api.openweathermap.org"
```

**`examples/multi-tool/math_tools.py`:**
```python
"""
Multiple tools in one file.
Each @tool decorated function becomes a separate tool.
"""
from fastmcp.tools import tool


@tool
def add(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum of a and b.
    """
    return a + b


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The product of a and b.
    """
    return a * b
```

**No file exceeds ~200 lines.** MCP transport is split by responsibility (session, stream, methods, legacy adapter). Registry is split into 3. Manager tools are one file per domain.

---

## Secrets Store

### Storage

- `/data/secrets.enc`: encrypted values only.
- `/data/secrets.meta.yaml`: plaintext metadata (keys + scope + status), never values.
- `/data/secrets.lock`: file lock to guarantee single-writer, atomic updates.

`secrets.meta.yaml` is safe to inspect and can contain placeholders:

```yaml
global:
  GITHUB_TOKEN:
    status: set
  OPENAI_API_KEY:
    status: placeholder

namespaces:
  slack:
    SLACK_BOT_TOKEN:
      status: placeholder
```

`secrets.enc` contains the actual values in encrypted form and is never edited directly.

### Encryption

- Envelope format: `{version, kdf, salt, nonce, ciphertext, created_at}`.
- KDF: PBKDF2-HMAC-SHA256 from `SECRETS_KEY`.
- Cipher: Fernet-compatible authenticated encryption via `cryptography`.
- Production default: `SECRETS_KEY` required. Local-only override: `ALLOW_INSECURE_SECRETS=1`.
- Manager writes encrypted payload; core reads/decrypts only.

### Safe Human Editing Workflow

Secrets values are never provided through MCP tools.

1. LLM calls `prepare_secret("GITHUB_TOKEN")` to create placeholder metadata.
2. Human sets value from terminal (recommended):
   `docker exec -it tooldock-manager python -m app.cli.secrets set --key GITHUB_TOKEN --scope global`
3. Optional bulk edit:
   `docker exec -it tooldock-manager python -m app.cli.secrets edit`
4. `secrets edit` flow:
   - Acquire `/data/secrets.lock`
   - Decrypt to `0600` temp file in tmpfs (`/dev/shm` or `/tmp`)
   - Open `$EDITOR`
   - Validate schema + required keys
   - Re-encrypt and atomically replace `/data/secrets.enc`
   - Securely delete temp file
5. LLM calls `reload_core()` after user confirms save.

### How secrets reach tools

```
Startup / Reload
       │
       ▼
  core reads /data/secrets.meta.yaml + /data/secrets.enc
       │
       ▼
  Decrypts in-memory
       │
       ▼
  Stores merged secrets map: {namespace: {KEY: VALUE}}
       │
       ▼
  For each namespace worker:
    1. Merge global + namespace + tooldock.yaml env defaults
    2. Spawn worker process with that env
    3. Core dispatches tool calls over worker RPC
    4. On secret change, restart only affected workers
```

No global `os.environ` mutation in core request handlers. Isolation is process-level.

### Manager tools for secrets

**Secrets values never flow through LLM chat.** MCP tools only manage placeholders/status.

```
prepare_secret(key: str, namespace: str | None = None) → dict
    Creates placeholder metadata with status "placeholder".
    Returns: {"key": "GITHUB_TOKEN", "scope": "global",
              "meta_file": "/data/secrets.meta.yaml",
              "instructions": "Run: docker exec -it tooldock-manager python -m app.cli.secrets set --key GITHUB_TOKEN --scope global"}
    LLM instructs user to run the command; value never touches chat.

list_secrets(namespace: str | None = None) → list[dict]
    List status only: {"key": "GITHUB_TOKEN", "scope": "global", "status": "set" | "placeholder" | "missing"}
    Never shows values, not even masked. Just whether it's configured or still a placeholder.

remove_secret(key: str, namespace: str | None = None) → dict
    Remove metadata + encrypted value entry. Signals core reload.

check_secrets(namespace: str) → dict
    Reads tooldock.yaml for the namespace, compares declared secrets vs available.
    Returns: {"satisfied": ["GITHUB_TOKEN"], "missing": ["SLACK_TOKEN"],
              "placeholders": ["AWS_KEY"]}
    Tells LLM exactly which keys still need human `secrets set`.
```

**Flow when installing a namespace that needs secrets:**
1. LLM calls `check_secrets("github")` → `{"missing": ["GITHUB_TOKEN"]}`
2. LLM calls `prepare_secret("GITHUB_TOKEN")` → placeholder created
3. LLM tells user to run:
   `docker exec -it tooldock-manager python -m app.cli.secrets set --key GITHUB_TOKEN --scope global`
4. User sets value interactively (no-echo input, never printed)
5. LLM calls `reload_core()` → core picks up the new secret
6. LLM calls `check_secrets("github")` → `{"satisfied": ["GITHUB_TOKEN"]}`

---

## Endpoints

### Core (port 8000)

| Endpoint | Method | Headers | Purpose |
|----------|--------|---------|---------|
| `/mcp` | POST | `Authorization`, `X-Namespace`, `Content-Type`, `Accept`, `MCP-Protocol-Version*`, `Mcp-Session-Id*` | Streamable HTTP JSON-RPC |
| `/mcp` | GET | `Authorization`, `X-Namespace`, `Mcp-Session-Id` | Optional SSE stream |
| `/mcp` | DELETE | `Authorization`, `X-Namespace`, `Mcp-Session-Id` | Session termination |
| `/sse` | GET | `Authorization`, `X-Namespace` | Legacy HTTP+SSE compatibility |
| `/messages` | POST | `Authorization`, `X-Namespace` | Legacy client-to-server messages |
| `/tools` | GET | `Authorization`, `X-Namespace` | List tools (REST) |
| `/tools/{name}` | POST | `Authorization`, `X-Namespace` | Call tool (REST) |
| `/tools/{name}/schema` | GET | `Authorization`, `X-Namespace` | Tool input schema |
| `/health` | GET | — | Health check |
| `/namespaces` | GET | `Authorization` | List available namespaces |
| `/reload` | POST | `Authorization`, `X-Manager-Token` | Reload signal from manager only |

\* Client should send `MCP-Protocol-Version` after initialize. If absent, server uses negotiated session version; if no version context exists, fallback is `2025-03-26`.

**Streamable HTTP behavior (SOTA MCP):**
- `POST /mcp` requires `Content-Type: application/json`.
- `POST /mcp` for `2025-06-18` and `2025-11-25` requires `Accept` to include both `application/json` and `text/event-stream`.
- `POST /mcp` for `2025-03-26` compatibility accepts `Accept: application/json` (or both).
- `POST /mcp` for `2025-06-18` and `2025-11-25` accepts exactly one JSON-RPC request object.
- `POST /mcp` for `2025-03-26` compatibility may accept JSON-RPC batch arrays.
- Notifications return `202 Accepted` with empty body.
- `Mcp-Session-Id` is issued on initialize response and required for subsequent stateful calls.
- Client must send `notifications/initialized` after successful `initialize`.
- If `Origin` header is present and not allowlisted, return `403`.
- If protocol version is unsupported, return `400`.
- If `Accept` is invalid for the negotiated protocol version, return `406`.
- If `Content-Type` is not `application/json`, return `415`.
- If auth missing/invalid, return `401` and include `WWW-Authenticate: Bearer`.

**SSE + resumability:**
- SSE messages include event IDs for resumability.
- `Last-Event-ID` allows replay from server buffer window.
- Multiple SSE streams per session are allowed.

**Tools method compliance:**
- `tools/list` returns full metadata: `name`, `title`, `description`, `inputSchema`, optional `outputSchema`, optional `annotations`.
- `tools/call` returns structured content blocks and sets `isError=true` for tool-level failures.
- On registry changes, server emits `notifications/tools/list_changed`.

**Protocol version handling:**
- Supported: `2025-11-25` (default), `2025-06-18` (compatibility), `2025-03-26` (legacy compatibility).
- Initialize negotiates protocol version and pins it to session state.
- For subsequent requests:
  - If header exists, it must match negotiated session version.
  - If header is absent, session version is used.
  - If no session exists and no header exists, server assumes `2025-03-26` compatibility mode.

**Legacy compatibility (older MCP clients):**
- `GET /sse` opens stream and emits `endpoint` event pointing to `/messages`.
- `POST /messages?session_id=...` accepted for legacy clients.
- Legacy paths are optional via `ENABLE_LEGACY_MCP=true`.

**`/reload` security (both controls required):**
- Valid bearer token.
- Valid `X-Manager-Token` shared secret.
- Source IP in `INTERNAL_ALLOWED_CIDRS` (default manager internal IP `172.30.0.10/32`); otherwise `403`.

### Manager (port 8001)

Single MCP endpoint serving management tools. Same streamable HTTP semantics as core.

| Endpoint | Method | Headers | Purpose |
|----------|--------|---------|---------|
| `/mcp` | POST | `Authorization`, `Content-Type`, `Accept`, `MCP-Protocol-Version*`, `Mcp-Session-Id*` | MCP JSON-RPC (_system tools) |
| `/mcp` | GET | `Authorization`, `Mcp-Session-Id` | MCP SSE stream |
| `/sse` | GET | `Authorization` | Optional legacy compatibility |
| `/messages` | POST | `Authorization` | Optional legacy compatibility |
| `/health` | GET | — | Health check |

Manager tools exposed via MCP. Every tool description is written so any LLM (not just Claude) understands exactly what to do, step by step.
Manager follows the same protocol-version and `Accept` semantics as core.

---

#### Namespace Management

**`list_namespaces`**
```
Description: List all available tool namespaces. Returns each namespace's name,
how many tools it contains, whether it has a requirements.txt file, and whether
all required secrets are configured. Use this as your first step to understand
what is currently installed.

Parameters: none

Returns: List of objects, each with:
  - name (string): Namespace name, e.g. "github"
  - tool_count (integer): Number of tools loaded
  - has_requirements (boolean): Whether a requirements.txt exists
  - secrets_status (string): "ok" | "missing" | "placeholders" | "no_secrets_needed"

Example return:
  [{"name": "shared", "tool_count": 2, "has_requirements": false, "secrets_status": "no_secrets_needed"},
   {"name": "github", "tool_count": 5, "has_requirements": true, "secrets_status": "ok"}]
```

**`create_namespace`**
```
Description: Create a new empty namespace. This creates a directory on the volume
where you can then write tool files into. After creating a namespace, use
write_tool to add tools, then reload_core to make them available.

Parameters:
  - name (string, required): Namespace name. Must be lowercase, may contain
    hyphens. Cannot be "_system" (reserved). Examples: "github", "my-tools",
    "devops".

Returns: {"created": true, "path": "/data/tools/github"}

Errors:
  - Name already exists → error with existing path
  - Invalid name (uppercase, dots, spaces) → validation error
```

**`delete_namespace`**
```
Description: Permanently delete a namespace, all its tool files, and its installed
dependencies. This cannot be undone. The namespace will disappear from the core
after the next reload.

Parameters:
  - name (string, required): Namespace to delete. Cannot be "_system".

Returns: {"deleted": true, "name": "github"}

After calling: Call reload_core() to update the core server.
```

**`reload_core`**
```
Description: Signal the core server to rescan all namespaces and reload tools.
Call this after any change: creating/deleting namespaces, writing/deleting tools,
installing dependencies, or configuring secrets. The core will:
  1) rescan namespace directories,
  2) ensure each namespace venv exists,
  3) sync venv if requirements hash changed,
  4) restart only changed workers,
  5) atomically swap active registry snapshot.

Core process stays up; only namespace workers recycle as needed.

Parameters: none

Returns: {"reloaded": true, "namespaces": ["shared", "github", ...],
          "workers_restarted": ["github"], "deps_synced": ["github"]}
```

---

#### Tool File Management

**`list_tools`**
```
Description: List all tools in a specific namespace. Returns each tool's name,
its description (from the docstring), and which .py file it is defined in.
Use this to understand what tools exist before modifying them.

Parameters:
  - namespace (string, required): Namespace to list tools for. Example: "github"

Returns: List of objects, each with:
  - name (string): Tool name, e.g. "list_issues"
  - description (string): Tool description from its docstring
  - filename (string): File that contains this tool, e.g. "issues.py"

Example return:
  [{"name": "list_issues", "description": "List GitHub issues for a repository.", "filename": "issues.py"},
   {"name": "create_issue", "description": "Create a new GitHub issue.", "filename": "issues.py"}]
```

**`get_tool_source`**
```
Description: Read the full Python source code of a tool file. Use this to
inspect existing tools, understand their implementation, or before modifying them.

Parameters:
  - namespace (string, required): Namespace the file belongs to. Example: "github"
  - filename (string, required): Python filename. Example: "issues.py"

Returns: {"filename": "issues.py", "source": "import os\nfrom fastmcp.tools import tool\n..."}
```

**`write_tool`**
```
Description: Write a Python tool file to a namespace. The file must contain at
least one function decorated with @tool from fastmcp. The code is validated
before writing:
  1. Syntax check (must be valid Python)
  2. Must contain at least one @tool decorator
  3. Must have type hints on all parameters
  4. Must have a docstring on each @tool function

If validation fails, the file is NOT written and the error is returned.
After writing, call reload_core() to make the tool available.

IMPORTANT: Follow this exact pattern for every tool:

    from fastmcp.tools import tool

    @tool
    async def my_tool(param: str, count: int = 10) -> dict:
        """Clear description of what this tool does.

        Args:
            param: What this parameter is for.
            count: What this parameter controls. Defaults to 10.

        Returns:
            Description of what is returned.
        """
        # implementation here
        return {"result": "value"}

Parameters:
  - namespace (string, required): Target namespace. Example: "github"
  - filename (string, required): Filename to write. Must end in .py. Example: "issues.py"
  - code (string, required): Complete Python source code for the file.

Returns on success: {"written": true, "filename": "issues.py", "tools_found": ["list_issues", "create_issue"]}
Returns on validation error: {"written": false, "error": "No @tool decorator found", "details": "..."}

After calling: Call reload_core() to make changes live.
```

**`delete_tool`**
```
Description: Delete a tool file from a namespace. This removes the .py file
permanently. All tools defined in that file will be removed.
After deleting, call reload_core() to update the core.

Parameters:
  - namespace (string, required): Namespace. Example: "github"
  - filename (string, required): File to delete. Example: "issues.py"

Returns: {"deleted": true, "filename": "issues.py"}
```

---

#### Dependencies

**`install_requirements`**
```
Description: Install all Python packages listed in a namespace's requirements.txt
file into that namespace's dedicated virtualenv at /data/venvs/{namespace}/.
Each namespace has its own interpreter and site-packages, so dependencies are
fully isolated.

This is an explicit sync command. `reload_core()` also performs sync automatically
when requirements hash changed.

After installing, call reload_core() so the worker restarts with updated deps.

Parameters:
  - namespace (string, required): Namespace whose requirements.txt to install.

Returns on success: {"installed": true, "namespace": "github", "packages": ["httpx>=0.28.0"]}
Returns on error: {"installed": false, "error": "pip install failed", "details": "..."}
```

**`add_requirement`**
```
Description: Add a single Python package to a namespace's requirements.txt and
sync the namespace venv immediately. If requirements.txt doesn't exist yet,
it is created.

Parameters:
  - namespace (string, required): Target namespace.
  - package (string, required): Package specifier. Examples: "httpx", "httpx>=0.28.0", "beautifulsoup4==4.12.0"

Returns: {"added": true, "package": "httpx>=0.28.0", "namespace": "github"}

After calling: Call reload_core() to restart worker with updated environment.
```

**`list_requirements`**
```
Description: Show the contents of a namespace's requirements.txt file.
Returns an empty list if the file doesn't exist.

Parameters:
  - namespace (string, required): Namespace to check.

Returns: {"namespace": "github", "packages": ["httpx>=0.28.0", "beautifulsoup4"]}
```

---

#### Secrets (values never pass through chat)

**`prepare_secret`**
```
Description: Create a placeholder entry for a secret in the secrets store.
This updates metadata only. The user sets the real value via manager CLI.
This tool NEVER accepts or returns actual secret values.

IMPORTANT: After calling this, you MUST tell the user:
  "Run: docker exec -it tooldock-manager python -m app.cli.secrets set
   --key {key} --scope {scope}"

Parameters:
  - key (string, required): Secret name. Examples: "GITHUB_TOKEN", "OPENAI_API_KEY"
  - namespace (string or null, optional): If set, the secret is scoped to this
    namespace only. If null/omitted, the secret is global (available to all namespaces).

Returns: {"key": "GITHUB_TOKEN", "scope": "global", "meta_file": "/data/secrets.meta.yaml",
          "instructions": "Run: docker exec -it tooldock-manager python -m app.cli.secrets set --key GITHUB_TOKEN --scope global"}

After the user sets the value: Call reload_core() to load the new secret.
```

**`list_secrets`**
```
Description: List all configured secrets and their status. Shows only key names
and whether they are configured or still placeholders. NEVER shows actual values.

Parameters:
  - namespace (string or null, optional): Filter to a specific namespace's secrets.
    If null/omitted, shows all secrets (global + all namespaces).

Returns: List of objects:
  [{"key": "GITHUB_TOKEN", "scope": "global", "status": "set"},
   {"key": "AWS_KEY", "scope": "devops", "status": "placeholder"}]

  status is one of:
    - "set": Value exists in encrypted payload
    - "placeholder": Key exists in metadata, value not set yet
```

**`remove_secret`**
```
Description: Remove a secret entry from the secrets store entirely.
After removing, call reload_core() to apply the change.

Parameters:
  - key (string, required): Secret key to remove.
  - namespace (string or null, optional): Scope. Null = global.

Returns: {"removed": true, "key": "GITHUB_TOKEN", "scope": "global"}
```

**`check_secrets`**
```
Description: Check whether a namespace has all the secrets it needs. Reads the
namespace's tooldock.yaml to find declared required secrets, then checks the
secrets store. Use this after installing a namespace to know if additional
secrets need to be configured.

Parameters:
  - namespace (string, required): Namespace to check.

Returns:
  {"namespace": "github",
   "satisfied": ["GITHUB_TOKEN"],
   "missing": ["SLACK_TOKEN"],
   "placeholders": ["AWS_KEY"]}

  - satisfied: Secrets that are properly configured
  - missing: Secrets that don't exist in the store at all
  - placeholders: Secrets that have metadata placeholders but no encrypted value yet

Next steps based on result:
  - For each "missing": call prepare_secret(key) then tell user to run secrets set
  - For each "placeholder": tell user to run secrets set for that key
  - When all are "satisfied": call reload_core() and the namespace is ready
```

---

#### Builder (LLM-driven translation)

These tools let you translate tool repositories (from any language) into Python
tools that ToolDock can run. The typical workflow is:

**Step-by-step translation workflow:**
1. Call `analyze_repo` to understand the source repository
2. Call `read_repo_file` for each relevant source file
3. Understand what each tool does (API calls, logic, parameters)
4. Call `create_namespace` for the target namespace
5. Call `add_requirement` for any Python packages needed (e.g. httpx)
6. Call `write_tool` for each translated Python tool file
7. Call `install_requirements` to install the dependencies
8. Call `reload_core` to load the new tools
9. Call `test_tool` for each tool to verify the translation works
10. Call `check_secrets` and `prepare_secret` for any required API tokens

**`analyze_repo`**
```
Description: Clone a git repository and analyze its structure. Returns information
about the repository's language, framework, what tools it defines, what
dependencies it has, and what external APIs it calls. Use this as the first step
when translating a tool repository to Python.

The repo is cloned to a temporary working area. It is NOT installed or executed.

Parameters:
  - repo_url (string, required): Git repository URL.
    Examples: "https://github.com/modelcontextprotocol/server-github",
              "https://github.com/someone/my-mcp-server"

Returns:
  {"repo_url": "...",
   "language": "typescript",
   "framework": "mcp-sdk",
   "files": ["src/index.ts", "src/tools/issues.ts", ...],
   "tools_found": [
     {"name": "list_issues", "file": "src/tools/issues.ts",
      "description": "List GitHub issues", "parameters": [...]},
     ...
   ],
   "dependencies": {"@octokit/rest": "^20.0.0", ...},
   "apis_called": ["api.github.com", ...],
   "secrets_needed": ["GITHUB_TOKEN"]}
```

**`read_repo_file`**
```
Description: Read the source code of a specific file from a previously analyzed
repository. Use this to understand the implementation details of each tool
before translating it to Python.

Parameters:
  - repo_url (string, required): Same repo URL used in analyze_repo.
  - path (string, required): File path within the repo. Example: "src/tools/issues.ts"

Returns: {"path": "src/tools/issues.ts", "content": "import { Octokit } from..."}
```

**`generate_tool`**
```
Description: This is an alias for write_tool, specifically named for the
translation workflow. Write a translated Python tool file to a namespace.
Same validation rules as write_tool apply. See write_tool for full details.

Parameters: Same as write_tool (namespace, filename, code)
Returns: Same as write_tool
```

**`test_tool`**
```
Description: Execute a single tool with test input and return the result.
Use this to verify that a translated tool works correctly. The tool runs
in the core server's environment with its namespace's secrets and dependencies.

If the tool fails, the error message and traceback are returned so you can
fix the translation.

Parameters:
  - namespace (string, required): Namespace the tool is in.
  - tool_name (string, required): Name of the tool to test. Example: "list_issues"
  - input (object, required): Input arguments as a JSON object.
    Example: {"owner": "anthropics", "repo": "claude-code", "state": "open"}

Returns on success: {"success": true, "result": {...tool output...}}
Returns on error: {"success": false, "error": "KeyError: 'GITHUB_TOKEN'",
                   "traceback": "Traceback (most recent call last):\n  ..."}
```

**`install_pip_packages`**
```
Description: Install Python packages into the manager's own environment.
Use this only if you need a package for analysis (e.g. a parser for a
specific language). For namespace tool dependencies, use add_requirement instead.

Parameters:
  - packages (list of strings, required): Package specifiers.
    Example: ["tree-sitter", "tree-sitter-typescript"]

Returns: {"installed": true, "packages": ["tree-sitter", "tree-sitter-typescript"]}
```

---

#### Installer (registry integration)

**`search_registry`**
```
Description: Search the MCP server registry for installable tool servers.
Returns a list of matching servers with their name, description, package type,
and source URL. Use this when the user wants to find and install existing
MCP servers.

Parameters:
  - query (string, required): Search term. Examples: "github", "slack", "database"

Returns: List of objects:
  [{"name": "server-github", "description": "GitHub API tools",
    "package": "@modelcontextprotocol/server-github", "package_type": "npm",
    "source_url": "https://github.com/modelcontextprotocol/server-github"},
   ...]
```

**`install_from_registry`**
```
Description: Begin the translation process for a package from the MCP registry.
This clones/downloads the source code and runs analyze_repo on it. It does NOT
automatically translate — you must then use read_repo_file and write_tool to
translate each tool to Python.

Parameters:
  - package (string, required): Package name from search results.
    Example: "@modelcontextprotocol/server-github"
  - namespace (string, required): Target namespace name for the translated tools.
    Example: "github"

Returns: Same as analyze_repo — the analysis of the source code.

Next steps: Follow the translation workflow (read source → write Python tools → test).
```

**`install_from_repo`**
```
Description: Begin the translation process for a git repository URL.
Clones the repo and runs analyze_repo. Same as install_from_registry but
takes a URL instead of a package name.

Parameters:
  - repo_url (string, required): Git URL. Example: "https://github.com/someone/my-tools"
  - namespace (string, required): Target namespace name.

Returns: Same as analyze_repo.

Next steps: Follow the translation workflow.
```

---

#### Introspection

**`health`**
```
Description: Check the health of both the manager and the core server.
Returns uptime, Python version, and connectivity status.

Parameters: none

Returns: {"manager_uptime": "2h 15m", "core_reachable": true,
          "python_version": "3.12.1", "namespaces_loaded": 5, "total_tools": 23}
```

**`server_config`**
```
Description: Show the current server configuration. Only shows non-sensitive
values (never shows BEARER_TOKEN or SECRETS_KEY).

Parameters: none

Returns: {"core_port": 8000, "manager_port": 8001, "data_dir": "/data",
          "log_level": "info", "cors_origins": "*", "mcp_session_ttl_hours": 24}
```

---

## MCP Transport Detail

Split into focused files with strict streamable HTTP behavior and legacy adapters:

### `app/mcp/jsonrpc.py` (~60 lines)

```python
# JSON-RPC 2.0 parsing and response building
def parse_request(body: bytes, protocol_version: str) -> JsonRpcRequest | list[JsonRpcRequest] | JsonRpcError
# 2025-06-18 and 2025-11-25: single request object only
# 2025-03-26 compatibility: batch array allowed
def success_response(id: Any, result: dict) -> dict
def error_response(id: Any, code: int, message: str) -> dict
def is_notification(request: JsonRpcRequest) -> bool
```

### `app/mcp/session.py` (~110 lines)

```python
# Session + protocol version lifecycle
class SessionManager:
    def create(self, protocol_version: str) -> str
    def validate(self, session_id: str, protocol_version: str | None) -> bool
    def get(self, session_id: str) -> SessionInfo
    def resolve_protocol(self, provided: str | None, session_id: str | None) -> str
    def terminate(self, session_id: str) -> None
    def evict_expired(self) -> int
```

### `app/mcp/stream.py` (~120 lines)

```python
# SSE replay buffer for resumability
class StreamManager:
    def append_event(self, session_id: str, event: SseEvent) -> str  # returns event_id
    def replay_from(self, session_id: str, last_event_id: str) -> list[SseEvent]
    def subscribe(self, session_id: str) -> AsyncIterator[SseEvent]
```

### `app/mcp/methods.py` (~140 lines)

```python
# MCP method dispatch
class McpMethods:
    def __init__(self, engine: ToolEngine):
        ...

    async def dispatch(self, method: str, params: dict, ns: str, session: SessionInfo | None) -> dict:
        """Route JSON-RPC method to handler."""

    async def initialize(self, params: dict, client_info: dict) -> dict
    # returns negotiated protocol version + capabilities
    async def notifications_initialized(self, session: SessionInfo) -> None
    async def tools_list(self, ns: str) -> dict
    async def tools_call(self, ns: str, name: str, arguments: dict) -> dict
    async def ping(self) -> dict
```

### `app/mcp/handler.py` (~180 lines)

```python
# HTTP-level handler
async def handle_mcp_post(request: Request, namespace: str, ...) -> Response:
    """POST /mcp streamable HTTP.
    - validate Content-Type: application/json
    - validate Accept against negotiated protocol version
    - validate bearer + origin + namespace + protocol/session headers
    - resolve protocol version (header -> session -> 2025-03-26 fallback)
    - dispatch method
    - return JSON or SSE stream response
    - notifications -> 202 with empty body
    """

async def handle_mcp_get(request: Request, namespace: str, ...) -> StreamingResponse:
    """GET /mcp optional SSE stream with replay support."""
    # validate Accept: text/event-stream
    # support Last-Event-ID replay
    # keepalive pings
    # multiple concurrent streams allowed

async def handle_mcp_delete(request: Request, ...) -> Response:
    """DELETE /mcp → session termination."""
```

### `app/mcp/legacy.py` (~110 lines)

```python
# Optional 2024-11-05 compatibility mode
async def handle_legacy_sse(request: Request, namespace: str) -> StreamingResponse:
    """GET /sse -> emits endpoint event with /messages URL."""

async def handle_legacy_messages(request: Request, namespace: str) -> Response:
    """POST /messages?session_id=... -> forward JSON-RPC to methods."""
```

**Total MCP transport: ~660 lines across 6 files.** Each file testable in isolation.

---

## OpenAPI Transport Detail

### `app/openapi/routes.py` (~80 lines)

```python
def create_router(engine: ToolEngine) -> APIRouter:
    router = APIRouter()

    @router.get("/tools")
    async def list_tools(x_namespace: str = Header()):
        return await engine.list_tools(x_namespace)

    @router.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request, x_namespace: str = Header()):
        body = await request.json()
        return await engine.call_tool(x_namespace, tool_name, body)

    @router.get("/tools/{tool_name}/schema")
    async def tool_schema(tool_name: str, x_namespace: str = Header()):
        return engine.get_schema(x_namespace, tool_name)

    return router
```

---

## Docker Setup

### `docker-compose.yml`

```yaml
services:
  tooldock-core:
    build:
      context: .
      dockerfile: core/Dockerfile
    ports:
      - "${CORE_PORT:-8000}:8000"
    user: "${TOOLDOCK_UID:-1000}:${TOOLDOCK_GID:-1000}"
    volumes:
      - tooldock-data:/data
    env_file: .env
    environment:
      - MANAGER_INTERNAL_TOKEN=${MANAGER_INTERNAL_TOKEN}
      - INTERNAL_ALLOWED_CIDRS=${INTERNAL_ALLOWED_CIDRS:-172.30.0.10/32,127.0.0.1/32}
      - ENABLE_LEGACY_MCP=${ENABLE_LEGACY_MCP:-true}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
    networks:
      tooldock-public: {}
      tooldock-internal:
        ipv4_address: 172.30.0.11
    restart: unless-stopped

  tooldock-manager:
    build:
      context: .
      dockerfile: manager/Dockerfile
    ports:
      - "${MANAGER_PORT:-8001}:8001"
    user: "${TOOLDOCK_UID:-1000}:${TOOLDOCK_GID:-1000}"
    volumes:
      - tooldock-data:/data
    tmpfs:
      - /dev/shm
    env_file: .env
    environment:
      - CORE_URL=http://172.30.0.11:8000
      - MANAGER_INTERNAL_TOKEN=${MANAGER_INTERNAL_TOKEN}
      - ENABLE_LEGACY_MCP=${ENABLE_LEGACY_MCP:-true}
      - ENABLE_FS_WATCHER=${ENABLE_FS_WATCHER:-false}
      - FS_WATCHER_DEBOUNCE_MS=${FS_WATCHER_DEBOUNCE_MS:-1500}
    depends_on:
      tooldock-core:
        condition: service_healthy
    networks:
      tooldock-public: {}
      tooldock-internal:
        ipv4_address: 172.30.0.10
    restart: unless-stopped

volumes:
  tooldock-data:
    driver: local

networks:
  tooldock-public:
    driver: bridge
  tooldock-internal:
    driver: bridge
    internal: true
    ipam:
      config:
        - subnet: 172.30.0.0/24
```

### `.env.example`

```bash
# Authentication
BEARER_TOKEN=change_me
MANAGER_INTERNAL_TOKEN=change_me_internal

# Ports
CORE_PORT=8000
MANAGER_PORT=8001
TOOLDOCK_UID=1000
TOOLDOCK_GID=1000

# Secrets encryption
SECRETS_KEY=
ALLOW_INSECURE_SECRETS=0

# Logging
LOG_LEVEL=info
LOG_RETENTION_DAYS=30

# CORS
CORS_ORIGINS=*
INTERNAL_ALLOWED_CIDRS=172.30.0.10/32,127.0.0.1/32

# MCP
MCP_SESSION_TTL_HOURS=24
MCP_SUPPORTED_VERSIONS=2025-11-25,2025-06-18,2025-03-26
ENABLE_LEGACY_MCP=true

# Manager watcher
ENABLE_FS_WATCHER=false
FS_WATCHER_DEBOUNCE_MS=1500
```

### `core/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ .
EXPOSE 8000
# Runtime user is set in docker-compose via TOOLDOCK_UID/TOOLDOCK_GID.
CMD ["python", "main.py"]
```

### `manager/Dockerfile`

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY manager/ .
EXPOSE 8001
CMD ["python", "main.py"]
```

Manager needs `git` for cloning repos. Core doesn't.

### `core/requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.10.0
pydantic-settings>=2.6.0
fastmcp==2.14.5
httpx>=0.28.0
pyyaml>=6.0.2
python-dotenv>=1.0.0
cryptography>=43.0.0
```

### `manager/requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.10.0
pydantic-settings>=2.6.0
fastmcp==2.14.5
httpx>=0.28.0
pyyaml>=6.0.2
python-dotenv>=1.0.0
cryptography>=43.0.0
GitPython>=3.1.0
```

---

## Configuration

### `app/config.py` (both core and manager, ~30 lines each)

```python
from pydantic_settings import BaseSettings

class CoreSettings(BaseSettings):
    bearer_token: str
    manager_internal_token: str
    data_dir: str = "/data"
    log_level: str = "info"
    cors_origins: str = "*"
    internal_allowed_cidrs: str = "172.30.0.10/32,127.0.0.1/32"
    mcp_session_ttl_hours: int = 24
    mcp_supported_versions: str = "2025-11-25,2025-06-18,2025-03-26"
    enable_legacy_mcp: bool = True
    secrets_key: str | None = None
    allow_insecure_secrets: bool = False
    port: int = 8000

class ManagerSettings(BaseSettings):
    bearer_token: str
    core_url: str = "http://172.30.0.11:8000"
    manager_internal_token: str
    enable_fs_watcher: bool = False
    fs_watcher_debounce_ms: int = 1500
    port: int = 8001
```

No magic. All from env vars. Pydantic validates at startup.

---

## Test Strategy

### Test structure mirrors source

```
tests/
├── conftest.py                     # ~80 lines
│   - tmp_data_dir fixture (creates tools/, venvs/, workers/, etc.)
│   - sample_tool_file fixture (writes a .py with @tool)
│   - test_client fixture (FastAPI TestClient for core)
│   - secrets fixtures (writes test secrets.meta.yaml + secrets.enc)
│
├── core/
│   ├── test_scanner.py             # ~100 lines
│   │   - discovers namespaces from directories
│   │   - ignores dotfiles, underscored dirs
│   │   - empty dir = empty namespace
│   │
│   ├── test_loader.py              # ~120 lines
│   │   - imports .py files, extracts @tool functions
│   │   - skips files without @tool
│   │   - handles import errors gracefully
│   │   - parses metadata without global sys.path mutation
│   │
│   ├── test_worker_rpc.py          # ~120 lines
│   │   - worker startup and ready handshake
│   │   - tools.call request/response protocol
│   │   - timeout + cancellation behavior
│   │   - error code mapping contract
│   │
│   ├── test_engine.py              # ~120 lines
│   │   - list_tools returns correct tools
│   │   - call_tool executes in namespace worker
│   │   - call_tool validates input
│   │   - unknown namespace → NamespaceNotFound
│   │   - unknown tool → ToolNotFound
│   │   - namespace timeout/concurrency limits enforced
│   │
│   ├── test_secrets.py             # ~120 lines
│   │   - loads encrypted secrets.enc + metadata file
│   │   - merges global + namespace secrets
│   │   - namespace overrides global
│   │   - missing file → empty secrets (no crash)
│   │   - placeholder metadata treated as not configured
│   │   - secret file lock + atomic replace logic
│   │
│   ├── test_auth.py                # ~60 lines
│   │   - valid bearer → 200
│   │   - missing bearer → 401
│   │   - wrong bearer → 401
│   │   - /health skips auth
│   │
│   ├── test_mcp_jsonrpc.py         # ~80 lines
│   │   - parses valid request
│   │   - rejects invalid JSON
│   │   - rejects missing method
│   │   - builds success/error responses
│   │   - detects notifications (no id)
│   │
│   ├── test_mcp_session.py         # ~80 lines
│   │   - create returns unique ID
│   │   - validate accepts valid session
│   │   - validate rejects unknown session
│   │   - terminate removes session
│   │   - evict_expired removes old sessions
│   │
│   ├── test_mcp_methods.py         # ~120 lines
│   │   - initialize returns capabilities + session
│   │   - notifications/initialized required before regular ops
│   │   - tools/list returns tool schemas
│   │   - tools/call executes tool
│   │   - tools/call with bad args → error
│   │   - ping → pong
│   │   - unknown method → method not found
│   │
│   ├── test_mcp_handler.py         # ~150 lines
│   │   - POST with valid JSON-RPC → 200 + JSON
│   │   - POST notification → 202 empty
│   │   - POST wrong content-type → 415
│   │   - POST missing Accept pair (json + sse) for 2025-11-25 → 406
│   │   - POST missing X-Namespace → 400
│   │   - POST unknown namespace → 404
│   │   - POST invalid MCP-Protocol-Version → 400
│   │   - POST missing MCP-Protocol-Version fallback behavior
│   │   - Origin validation (allowlist + deny) → 200/403
│   │   - GET with Accept: text/event-stream → SSE
│   │   - GET without Accept → 406
│   │   - Last-Event-ID replay behavior
│   │   - DELETE terminates session
│   │   - Mcp-Session-Id header flow
│   │   - Optional legacy routes: /sse and /messages
│   │
│   ├── test_openapi_routes.py      # ~100 lines
│   │   - GET /tools lists tools
│   │   - POST /tools/{name} calls tool
│   │   - GET /tools/{name}/schema returns schema
│   │   - missing X-Namespace → 400
│   │   - unknown tool → 404
│   │
│   └── test_gateway.py             # ~60 lines
│       - /health returns 200
│       - /namespaces lists loaded namespaces
│       - /reload requires bearer + manager token + CIDR allowlist
│
├── manager/
│   ├── test_namespaces.py          # ~80 lines
│   ├── test_tool_files.py          # ~100 lines
│   ├── test_dependencies.py        # ~80 lines
│   ├── test_secrets.py             # ~80 lines
│   ├── test_builder.py             # ~100 lines
│   └── test_installer.py           # ~80 lines
│
└── integration/
    ├── test_drop_in.py             # ~100 lines
    │   - Create dir with .py → namespace appears
    │   - Add requirements.txt → namespace venv synced
    │   - Delete dir → namespace gone after reload
    │
    ├── test_mcp_compliance.py      # ~200 lines
    │   - Full streamable HTTP MCP compliance suite
    │   - Protocol version negotiation + header rules (2025-11-25)
    │   - Compatibility suite (2025-06-18 + 2025-03-26 fallback/batch acceptance)
    │   - Session lifecycle
    │   - Content-Type enforcement
    │   - SSE stream behavior + resume/replay
    │   - Optional legacy HTTP+SSE compatibility checks
    │
    ├── test_openapi_compliance.py  # ~80 lines
    │   - Correct status codes
    │   - Schema validation
    │   - Error format consistency
    │
    └── test_core_manager.py        # ~100 lines
        - manager reload signal accepted only with token + allowed source IP
        - watcher-triggered reload path
        - worker restart scope (changed namespaces only)
```

**~2,200 test lines across ~21-23 test files.** Average ~100 lines per file.

### Running tests

```bash
# All tests
pytest tests/ -v

# Core only
pytest tests/core/ -v

# Manager only
pytest tests/manager/ -v

# Integration only
pytest tests/integration/ -v

# Specific domain
pytest tests/core/test_mcp_handler.py -v
```

---

## Line Count Summary

Approximate after hardening updates:

- Core: ~1,250 lines (adds worker supervisor, stream replay, legacy adapter, internal security guard).
- Manager: ~1,280 lines (adds human secret CLI and venv-first dependency management).
- Tests: ~2,200 lines (adds protocol/version/origin/resume/legacy coverage).
- Total: ~4,700 lines.

Guideline: keep individual modules around `<= 200` lines where practical; split by domain when larger.

---

## Implementation Order

### Phase 1 — Core Gateway

Get tools serving via MCP + OpenAPI.

1. Project skeleton: directories, requirements, Docker, .env
2. `app/config.py` — settings from env
3. `app/registry/models.py` — ToolEntry, NamespaceInfo
4. `app/registry/loader.py` — parse .py, extract @tool metadata
5. `app/registry/scanner.py` — scan dirs, call loader
6. `app/workers/*` — worker supervisor + RPC
7. `app/engine.py` — list_tools, call_tool via worker RPC
8. `app/secrets.py` — encrypted payload + metadata reads
9. `app/auth.py` + `app/security.py` — bearer + internal endpoint guards
10. `app/openapi/routes.py` — REST endpoints
11. `app/mcp/jsonrpc.py` — JSON-RPC parsing
12. `app/mcp/session.py` — session + protocol version management
13. `app/mcp/stream.py` — replayable SSE buffer
14. `app/mcp/methods.py` — MCP method handlers
15. `app/mcp/handler.py` + `app/mcp/legacy.py` — streamable + optional legacy HTTP+SSE
16. `app/gateway.py` — wire everything
17. `main.py` + Dockerfile
18. Tests for all above
19. Docker build, create `shared/hello.py`, verify MCP + REST

### Phase 2 — Manager

Separate container with management tools via MCP.

1. `app/server.py` — FastAPI + MCP
2. `app/core_client.py` — HTTP client to core
3. `app/tools/namespaces.py` — CRUD
4. `app/tools/tool_files.py` — read/write/delete
5. `app/tools/dependencies.py` — venv create/sync per namespace
6. `app/tools/secrets.py` — placeholder/list/check/remove only
7. `app/cli/secrets.py` — interactive human secret set/edit commands
8. `app/watcher.py` — optional auto-reload on filesystem changes
9. `app/tools/introspect.py` — health + config
10. Dockerfile, docker-compose integration
11. Tests

### Phase 3 — Builder

LLM-driven repo translation.

1. `app/repo/clone.py` — git clone + tree analysis
2. `app/repo/analyze.py` — detect lang, framework, tools, APIs
3. `app/tools/builder.py` — generate, validate, test tools
4. `app/tools/installer.py` — registry search + install flow
5. Tests

### Phase 4 — Dashboard (later, separate repo)

Optional UI container. Connects to core + manager APIs.

---

## Client Configuration Examples

### Claude Desktop

```json
{
  "mcpServers": {
    "tooldock-github": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer change_me",
        "X-Namespace": "github",
        "MCP-Protocol-Version": "2025-11-25"
      }
    },
    "tooldock-manager": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer change_me",
        "MCP-Protocol-Version": "2025-11-25"
      }
    }
  }
}
```

If your MCP SDK negotiates protocol version automatically, omit `MCP-Protocol-Version` from static config and let the SDK manage it after `initialize`.

### LiteLLM

```yaml
mcp_servers:
  - name: "github-tools"
    url: "http://tooldock-core:8000/mcp"
    headers:
      Authorization: "Bearer change_me"
      X-Namespace: "github"
      MCP-Protocol-Version: "2025-11-25"
  - name: "devops-tools"
    url: "http://tooldock-core:8000/mcp"
    headers:
      Authorization: "Bearer change_me"
      X-Namespace: "devops"
      MCP-Protocol-Version: "2025-11-25"
```

### curl (MCP Streamable HTTP)

```bash
# 1) Initialize session
curl -i -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"init-1","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

# Capture Mcp-Session-Id from response headers and reuse below.

# 2) Send notifications/initialized
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "MCP-Protocol-Version: 2025-11-25" \
  -H "Mcp-Session-Id: <session-id>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# 3) Call tools/list
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "MCP-Protocol-Version: 2025-11-25" \
  -H "Mcp-Session-Id: <session-id>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":"tools-1","method":"tools/list","params":{}}'
```

### curl (Legacy MCP HTTP+SSE)

```bash
# 1) Open legacy SSE stream
curl -N http://localhost:8000/sse \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "Accept: text/event-stream"

# 2) POST messages to the endpoint emitted by SSE "endpoint" event
curl -X POST "http://localhost:8000/messages?session_id=<session-id>" \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}'
```

### curl (OpenAPI)

```bash
# List tools in github namespace
curl http://localhost:8000/tools \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github"

# Call a tool
curl -X POST http://localhost:8000/tools/list_issues \
  -H "Authorization: Bearer change_me" \
  -H "X-Namespace: github" \
  -H "Content-Type: application/json" \
  -d '{"owner": "anthropics", "repo": "claude-code"}'
```
