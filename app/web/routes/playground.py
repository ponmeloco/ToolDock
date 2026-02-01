"""
Playground API Routes.

Provides endpoints for tool testing via different transports:
- Direct execution via registry (logged locally)
- MCP JSON-RPC format testing
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token
from app.errors import ToolError, ToolNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playground", tags=["playground"])


class ToolExecuteRequest(BaseModel):
    """Request to execute a tool."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: Dict[str, Any] = {}
    transport: str = "direct"  # "direct" or "mcp"


class ToolExecuteResponse(BaseModel):
    """Response from tool execution."""

    tool: str
    transport: str
    result: Any
    success: bool
    error: Optional[str] = None


class MCPRequest(BaseModel):
    """MCP JSON-RPC request format."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: str = "2.0"
    id: int = 1
    method: str
    params: Optional[Dict[str, Any]] = None


class MCPResponse(BaseModel):
    """MCP JSON-RPC response format."""

    jsonrpc: str = "2.0"
    id: int
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class ToolInfo(BaseModel):
    """Tool information for playground."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    type: str
    namespace: str


class ToolListResponse(BaseModel):
    """Response listing all available tools."""

    tools: List[ToolInfo]
    total: int


@router.get("/tools", response_model=ToolListResponse)
async def list_playground_tools(
    request: Request,
    _: str = Depends(verify_token),
) -> ToolListResponse:
    """
    List all available tools for the playground.

    Returns tools from all namespaces with their schemas.
    """
    registry = request.app.state.registry
    all_tools = registry.list_all()

    tools = [
        ToolInfo(
            name=t["name"],
            description=t["description"],
            input_schema=t["inputSchema"],
            type=t.get("type", "native"),
            namespace=t.get("namespace", "shared"),
        )
        for t in all_tools
    ]

    return ToolListResponse(tools=tools, total=len(tools))


@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(
    request: Request,
    body: ToolExecuteRequest,
    _: str = Depends(verify_token),
) -> ToolExecuteResponse:
    """
    Execute a tool and return the result.

    This endpoint logs the tool execution locally so it appears in the logs.

    Args:
        body: Tool name, arguments, and transport type
    """
    registry = request.app.state.registry

    logger.info(f"Playground executing tool: {body.tool_name} via {body.transport}")

    try:
        if body.transport == "mcp":
            # Execute via MCP-style call (same result, different logging)
            result = await registry.call(body.tool_name, body.arguments)
            return ToolExecuteResponse(
                tool=body.tool_name,
                transport="mcp",
                result={"content": [{"type": "text", "text": str(result)}]},
                success=True,
            )
        else:
            # Direct execution
            result = await registry.call(body.tool_name, body.arguments)
            return ToolExecuteResponse(
                tool=body.tool_name,
                transport="direct",
                result=result,
                success=True,
            )

    except ToolNotFoundError as e:
        logger.warning(f"Tool not found: {body.tool_name}")
        raise HTTPException(status_code=404, detail=str(e.message))

    except ToolError as e:
        logger.error(f"Tool error for {body.tool_name}: {e.message}")
        return ToolExecuteResponse(
            tool=body.tool_name,
            transport=body.transport,
            result=None,
            success=False,
            error=e.message,
        )

    except Exception as e:
        logger.error(f"Unexpected error executing {body.tool_name}: {e}", exc_info=True)
        return ToolExecuteResponse(
            tool=body.tool_name,
            transport=body.transport,
            result=None,
            success=False,
            error=str(e),
        )


@router.post("/mcp", response_model=MCPResponse)
async def mcp_test(
    request: Request,
    body: MCPRequest,
    _: str = Depends(verify_token),
) -> MCPResponse:
    """
    Test MCP JSON-RPC format requests.

    Supports:
    - tools/list: List all available tools
    - tools/call: Execute a tool

    This mimics the MCP protocol for testing purposes.
    """
    registry = request.app.state.registry

    logger.info(f"Playground MCP test: {body.method}")

    try:
        if body.method == "tools/list":
            # List tools
            all_tools = registry.list_all()
            tools = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"],
                }
                for t in all_tools
            ]
            return MCPResponse(
                jsonrpc="2.0",
                id=body.id,
                result={"tools": tools},
            )

        elif body.method == "tools/call":
            # Execute tool
            params = body.params or {}
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name:
                return MCPResponse(
                    jsonrpc="2.0",
                    id=body.id,
                    error={"code": -32602, "message": "Missing 'name' in params"},
                )

            result = await registry.call(tool_name, arguments)

            return MCPResponse(
                jsonrpc="2.0",
                id=body.id,
                result={
                    "content": [{"type": "text", "text": str(result)}],
                    "isError": False,
                },
            )

        elif body.method == "initialize":
            # Initialize response
            return MCPResponse(
                jsonrpc="2.0",
                id=body.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tooldock-playground", "version": "1.0.0"},
                },
            )

        else:
            return MCPResponse(
                jsonrpc="2.0",
                id=body.id,
                error={"code": -32601, "message": f"Method not found: {body.method}"},
            )

    except ToolNotFoundError as e:
        return MCPResponse(
            jsonrpc="2.0",
            id=body.id,
            error={"code": -32602, "message": e.message},
        )

    except ToolError as e:
        return MCPResponse(
            jsonrpc="2.0",
            id=body.id,
            result={
                "content": [{"type": "text", "text": f"Error: {e.message}"}],
                "isError": True,
            },
        )

    except Exception as e:
        logger.error(f"MCP test error: {e}", exc_info=True)
        return MCPResponse(
            jsonrpc="2.0",
            id=body.id,
            error={"code": -32603, "message": str(e)},
        )
