# ToolDock v2

ToolDock is a two-service tool platform for MCP clients and HTTP callers.

- `tooldock-core`: executes namespace tools (OpenAPI + MCP).
- `tooldock-manager`: manages namespaces, tool files, dependencies, and secrets metadata (MCP).

## Architecture

- Core container name: `tooldock-core`
- Manager container name: `tooldock-manager`
- Shared runtime data: `./.tooldock-data`
- Auth model:
  - `Authorization: Bearer <BEARER_TOKEN>` on all non-health endpoints.
  - `X-Manager-Token: <MANAGER_INTERNAL_TOKEN>` required for `POST /reload`.

## Quick Start

1. Prepare env:

```bash
cp .env.example .env
```

2. Set at least:
   - `BEARER_TOKEN`
   - `MANAGER_INTERNAL_TOKEN`

3. Start services:

```bash
bash scripts/start.sh
```

4. Check status:

```bash
bash scripts/status.sh
```

## Scripts

- Start (build + run): `bash scripts/start.sh`
- Start clean (wipe runtime leftovers first): `bash scripts/start.sh --clean`
- Start without rebuild: `bash scripts/start.sh --no-build`
- Status: `bash scripts/status.sh`
- Status + recent logs: `bash scripts/status.sh --logs --tail 100`
- Stop: `bash scripts/stop.sh`
- Stop + remove volumes: `bash scripts/stop.sh --volumes`
- Full clean helper only: `bash scripts/clean.sh`

## Ports

- Core: `http://localhost:${CORE_PORT}` (default `8000`)
- Manager: `http://localhost:${MANAGER_PORT}` (default `8001`)

You can override ports in `.env` or per command:

```bash
CORE_PORT=18000 MANAGER_PORT=18001 bash scripts/start.sh
```

## Endpoints

Core:
- `GET /health`
- `GET /namespaces`
- `POST /reload` (requires bearer + manager token)
- `GET /tools` with header `X-Namespace`
- `GET /tools/{tool_name}/schema` with header `X-Namespace`
- `POST /tools/{tool_name}` with header `X-Namespace`
- `POST/GET/DELETE /mcp` with header `X-Namespace`
- Optional legacy MCP: `GET /sse`, `POST /messages` (when enabled)

Manager:
- `GET /health`
- `POST/GET/DELETE /mcp`
- Optional legacy MCP: `GET /sse`, `POST /messages` (when enabled)

## Quick Smoke Test

Create a minimal namespace and tool:

```bash
mkdir -p .tooldock-data/tools/demo
cat > .tooldock-data/tools/demo/echo.py <<'PY'
def tool(fn):
    return fn

@tool
def echo(text: str) -> str:
    """Echo text."""
    return text
PY
```

Reload core:

```bash
curl -sS -X POST http://localhost:8000/reload \
  -H "Authorization: Bearer <BEARER_TOKEN>" \
  -H "X-Manager-Token: <MANAGER_INTERNAL_TOKEN>"
```

List and call:

```bash
curl -sS http://localhost:8000/tools \
  -H "Authorization: Bearer <BEARER_TOKEN>" \
  -H "X-Namespace: demo"

curl -sS -X POST http://localhost:8000/tools/echo \
  -H "Authorization: Bearer <BEARER_TOKEN>" \
  -H "X-Namespace: demo" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'
```

## OpenWebUI + LiteLLM

Recommended setup:

1. Keep your model path in OpenWebUI pointed at LiteLLM as usual.
2. Add ToolDock as MCP server(s) in OpenWebUI:
   - Manager MCP URL: `http://localhost:8001/mcp`
   - Core MCP URL: `http://localhost:8000/mcp`
3. Use these headers in MCP client config:
   - `Authorization: Bearer <BEARER_TOKEN>`
   - `Content-Type: application/json`
   - `Accept: application/json, text/event-stream`
   - `MCP-Protocol-Version: 2025-11-25`
   - For core only: `X-Namespace: <namespace>`

If OpenWebUI itself runs in Docker and cannot reach `localhost`, use host networking access from that container (for example `host.docker.internal`) or put both stacks on a shared Docker network.

## Notes

- Namespace names must be lowercase alphanumeric with optional hyphens (for example `github-tools`).
- Runtime tool files are loaded from `./.tooldock-data/tools/<namespace>/*.py`.
- Manager exposes many MCP tools such as `create_namespace`, `write_tool`, `install_requirements`, `reload_core`, and `test_tool`.
- Ready-to-use assistant system prompt: `SYSTEM_PROMPT_ASSISTANT.md`.
- Full ToolDock -> LiteLLM -> OpenWebUI workflow: `LITELLM_OPENWEBUI_E2E_WORKFLOW.md`.
