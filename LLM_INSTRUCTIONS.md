# LLM Instructions

## Role of the Model

The language model acts as an orchestrator that decides when to call tools.

Rules:
- Only use parameters defined in the tool schema
- Never invent parameters
- Prefer tools over guessing
- Treat tool responses as authoritative

## Tool Usage

Tools are discovered via OpenAPI.
Each tool corresponds to a POST endpoint under /tools/{tool_name}.
