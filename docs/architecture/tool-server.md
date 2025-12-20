# Tool Server

The tool server loads tools dynamically from a configured directory.
Each tool is registered in a ToolRegistry and exposed via OpenAPI.

The registry validates inputs using Pydantic models before execution.
