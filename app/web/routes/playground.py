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
from app.utils import set_request_context
from app.errors import ToolError, ToolNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playground", tags=["playground"])


class ToolExecuteRequest(BaseModel):
    """Request to execute a tool."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: Dict[str, Any] = {}
    transport: str = "openapi"  # "openapi", "mcp", or "direct"
    namespace: Optional[str] = None


class ToolExecuteResponse(BaseModel):
    """Response from tool execution."""

    tool: str
    transport: str
    result: Any
    success: bool
    error: Optional[str] = None
    error_type: Optional[str] = None  # "network" | "server" | "unknown"
    status_code: Optional[int] = None


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
    import os

    registry = request.app.state.registry
    set_request_context(tool_name=body.tool_name)
    logger.info(f"Playground executing tool: {body.tool_name} via {body.transport}")

    try:
        if body.transport == "direct":
            # Direct execution (registry only)
            result = await registry.call(body.tool_name, body.arguments)
            return ToolExecuteResponse(
                tool=body.tool_name,
                transport="direct",
                result=result,
                success=True,
            )

        # Proxy to real tool servers for transport-level testing
        token = os.getenv("BEARER_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        timeout = float(os.getenv("TOOL_TIMEOUT_SECONDS", "30"))

        import httpx

        if body.transport == "openapi":
            openapi_port = int(os.getenv("OPENAPI_PORT", "8006"))
            url = f"http://localhost:{openapi_port}/tools/{body.tool_name}"
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json=body.arguments, headers=headers)
            except httpx.RequestError as e:
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="openapi",
                    result=None,
                    success=False,
                    error=f"Network error: {e}",
                    error_type="network",
                )
            except httpx.TimeoutException as e:
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="openapi",
                    result=None,
                    success=False,
                    error=f"Network timeout: {e}",
                    error_type="network",
                )
            if res.status_code >= 400:
                try:
                    error = res.json()
                except Exception:
                    error = res.text
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="openapi",
                    result=None,
                    success=False,
                    error=str(error),
                    error_type="server",
                    status_code=res.status_code,
                )
            data = res.json()
            result = data.get("result", data)
            return ToolExecuteResponse(
                tool=body.tool_name,
                transport="openapi",
                result=result,
                success=True,
            )

        if body.transport == "mcp":
            namespace = body.namespace or "shared"
            mcp_port = int(os.getenv("MCP_PORT", "8007"))
            url = f"http://localhost:{mcp_port}/mcp/{namespace}"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": body.tool_name, "arguments": body.arguments},
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json=payload, headers=headers)
            except httpx.RequestError as e:
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="mcp",
                    result=None,
                    success=False,
                    error=f"Network error: {e}",
                    error_type="network",
                )
            except httpx.TimeoutException as e:
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="mcp",
                    result=None,
                    success=False,
                    error=f"Network timeout: {e}",
                    error_type="network",
                )
            if res.status_code >= 400:
                try:
                    error = res.json()
                except Exception:
                    error = res.text
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="mcp",
                    result=None,
                    success=False,
                    error=str(error),
                    error_type="server",
                    status_code=res.status_code,
                )
            data = res.json()
            if data.get("error"):
                return ToolExecuteResponse(
                    tool=body.tool_name,
                    transport="mcp",
                    result=None,
                    success=False,
                    error=data.get("error", {}).get("message", "MCP error"),
                    error_type="server",
                    status_code=res.status_code,
                )
            return ToolExecuteResponse(
                tool=body.tool_name,
                transport="mcp",
                result=data.get("result"),
                success=True,
            )

        raise HTTPException(status_code=400, detail=f"Unknown transport: {body.transport}")

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
            error_type="server",
        )

    except Exception as e:
        logger.error(f"Unexpected error executing {body.tool_name}: {e}", exc_info=True)
        return ToolExecuteResponse(
            tool=body.tool_name,
            transport=body.transport,
            result=None,
            success=False,
            error=str(e),
            error_type="unknown",
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
