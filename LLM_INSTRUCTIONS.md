# LLM Instructions

## Role of the Model

The language model acts as an orchestrator that decides when to call tools.

## Rules

- Only use parameters defined in the tool schema
- Never invent parameters
- Prefer tools over guessing
- Treat tool responses as authoritative
- Do not hallucinate tool capabilities

## Tool Discovery

Tools can be discovered via two transports:

### OpenAPI (Port 8006)
- `GET /tools` - List all available tools (requires Bearer token)
- `POST /tools/{tool_name}` - Execute a tool
- Tools appear as POST endpoints with JSON body

### MCP Streamable HTTP (Port 8007)
- `POST /mcp` with `{"method": "tools/list"}` - List tools
- `POST /mcp` with `{"method": "tools/call", "params": {"name": "...", "arguments": {...}}}` - Execute
- Uses JSON-RPC 2.0 protocol

## Tool Execution

Both transports use the same underlying tools. A tool call requires:

1. **Tool name** - Exact name as listed
2. **Arguments** - JSON object matching the input schema exactly

## Error Handling

- Invalid parameters return validation errors
- Unknown tools return "tool not found"
- Execution errors are returned as structured error objects

## Adding New Tools

See [how-to-add-a-tool-with-a-llm.md](how-to-add-a-tool-with-a-llm.md) for detailed instructions on generating tools with an LLM.
