# ToolDock -> LiteLLM -> OpenWebUI End-to-End Workflow

This runbook covers the full path:
`start ToolDock -> add MCP servers in LiteLLM -> connect OpenWebUI -> add system prompt -> create assistant -> test in chat -> stop`.

## 1. Start ToolDock

1. Prepare env:

```bash
cp .env.example .env
```

2. Set at least these values in `.env`:

- `BEARER_TOKEN=<your_token>`
- `MANAGER_INTERNAL_TOKEN=<your_internal_token>`

3. Start services:

```bash
bash scripts/start.sh
```

4. Check status:

```bash
bash scripts/status.sh
```

5. Optional health checks:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8001/health
```

## 2. Add ToolDock MCP servers in LiteLLM

Use your host IP if LiteLLM runs in another container/VM.
Example placeholder: `<HOST_IP>`.

Add two MCP servers in LiteLLM:

1. `tooldock-manager`
- URL: `http://<HOST_IP>:8001/mcp`
- Method/transport: `POST/GET/DELETE` JSON-RPC over HTTP
- Headers:
  - `Authorization: Bearer <BEARER_TOKEN>`
  - `Content-Type: application/json`
  - `Accept: application/json, text/event-stream`
  - `MCP-Protocol-Version: 2025-11-25`

2. `tooldock-core`
- URL: `http://<HOST_IP>:8000/mcp`
- Method/transport: `POST/GET/DELETE` JSON-RPC over HTTP
- Headers:
  - `Authorization: Bearer <BEARER_TOKEN>`
  - `Content-Type: application/json`
  - `Accept: application/json, text/event-stream`
  - `MCP-Protocol-Version: 2025-11-25`
  - `X-Namespace: demo` (or your target namespace)

Important:
- Core tool calls need `X-Namespace`.
- Manager does not need `X-Namespace`.

## 3. Connect OpenWebUI to LiteLLM

In OpenWebUI Admin settings:

1. Add LiteLLM as OpenAI-compatible backend.
2. Use base URL:
- `http://<LITELLM_HOST>:<LITELLM_PORT>/v1`
3. Set LiteLLM API key.
4. Save and verify model list is visible in OpenWebUI.

## 4. Add System Prompt and Create Assistant in OpenWebUI

1. Open `SYSTEM_PROMPT_ASSISTANT.md`.
2. In OpenWebUI, create a new Assistant.
3. Select a model served by LiteLLM.
4. Paste full content of `SYSTEM_PROMPT_ASSISTANT.md` into the assistant system prompt field.
5. Enable/select MCP tools exposed through LiteLLM:
- `tooldock-manager`
- `tooldock-core`
6. Save assistant.

## 5. First Chat Test Flow

Use this exact test sequence in chat:

1. Send:
- `Call a_first_call_instructions and summarize the required params for create_namespace and write_tool.`

2. Send:
- `Create namespace demo, write a tool file echo.py with one tool echo(text: str) -> str, then reload core and test_tool echo with input {"text":"hello"}.`

3. Expected result:
- Manager shows required params in tool metadata.
- Namespace/tool creation succeeds.
- `reload_core` succeeds.
- `test_tool` returns success and `hello`.

## 6. Direct MCP Sanity Check (optional)

Check manager tool schemas from terminal:

```bash
curl -sS -X POST "http://localhost:8001/mcp" \
  -H "Authorization: Bearer <BEARER_TOKEN>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2025-11-25" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}' | jq
```

Then call `notifications/initialized` and `tools/list` with returned `sessionId` if your client requires explicit session handling.

## 7. Stop Services

Stop stack:

```bash
bash scripts/stop.sh
```

Stop and remove volumes:

```bash
bash scripts/stop.sh --volumes
```

## 8. Common Issues

- `401 Unauthorized`
  - Check `Authorization` header and token value in `.env`.

- `core_reachable: false` in manager health
  - Check `tooldock-core` container health and port mapping.

- No tools visible in core MCP
  - Ensure `X-Namespace` header is set and namespace has valid tool files.

- OpenWebUI cannot reach localhost services
  - Use host IP or `host.docker.internal` depending on your platform/networking.

