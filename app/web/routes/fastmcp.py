"""FastMCP external server management routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import os

import httpx

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import verify_token
from app.db.database import get_db
from app.db.models import ExternalFastMCPServer
from app.external.fastmcp_manager import FastMCPServerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fastmcp", tags=["fastmcp"])

_fastmcp_manager: Optional[FastMCPServerManager] = None


async def _fanout_fastmcp_reload() -> Dict[str, Any]:
    if os.getenv("PYTEST_CURRENT_TEST") is not None:
        return {"status": "skipped", "reason": "test_mode"}

    token = os.getenv("BEARER_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    host = os.getenv("HOST", "127.0.0.1")
    if host in {"0.0.0.0", ""}:
        host = "127.0.0.1"
    openapi_port = os.getenv("OPENAPI_PORT", "8006")
    mcp_port = os.getenv("MCP_PORT", "8007")

    targets = {
        "openapi": f"http://{host}:{openapi_port}/admin/fastmcp/reload",
        "mcp": f"http://{host}:{mcp_port}/admin/fastmcp/reload",
    }

    results: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=0.5) as client:
        for name, url in targets.items():
            try:
                resp = await client.post(url, headers=headers)
                if resp.status_code >= 400:
                    results[name] = {"status": "error", "code": resp.status_code}
                else:
                    results[name] = {"status": "ok"}
            except Exception as exc:
                results[name] = {"status": "error", "error": str(exc)}
    return results


def set_fastmcp_context(manager: FastMCPServerManager) -> None:
    global _fastmcp_manager
    _fastmcp_manager = manager


class AddFastMCPServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_name: str = Field(..., min_length=3)
    namespace: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    version: Optional[str] = None


class FastMCPServerResponse(BaseModel):
    id: int
    server_name: str
    namespace: str
    version: Optional[str]
    install_method: str
    repo_url: Optional[str]
    entrypoint: Optional[str]
    port: Optional[int]
    status: str
    pid: Optional[int]
    last_error: Optional[str]


@router.get("/registry/servers")
async def list_registry_servers(
    limit: int = 30,
    cursor: Optional[str] = None,
    search: Optional[str] = None,
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        return await _fastmcp_manager.list_registry_servers(limit=limit, cursor=cursor, search=search)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/registry/health")
async def registry_health(_: str = Depends(verify_token)) -> Dict[str, Any]:
    if _fastmcp_manager is None:
        return {"status": "offline", "reason": "manager_not_initialized"}

    try:
        await _fastmcp_manager.list_registry_servers(limit=1)
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "offline", "reason": str(exc)}


@router.get("/servers", response_model=List[FastMCPServerResponse])
async def list_fastmcp_servers(_: str = Depends(verify_token)) -> List[FastMCPServerResponse]:
    with get_db() as db:
        rows = db.execute(select(ExternalFastMCPServer)).scalars().all()
        return [
            FastMCPServerResponse(
                id=row.id,
                server_name=row.server_name,
                namespace=row.namespace,
                version=row.version,
                install_method=row.install_method,
                repo_url=row.repo_url,
                entrypoint=row.entrypoint,
                port=row.port,
                status=row.status,
                pid=row.pid,
                last_error=row.last_error,
            )
            for row in rows
        ]


@router.post("/servers", response_model=FastMCPServerResponse)
async def add_fastmcp_server(request: AddFastMCPServerRequest, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        record = await _fastmcp_manager.add_server_from_registry(
            server_name=request.server_name,
            namespace=request.namespace,
            version=request.version,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = FastMCPServerResponse(
        id=record.id,
        server_name=record.server_name,
        namespace=record.namespace,
        version=record.version,
        install_method=record.install_method,
        repo_url=record.repo_url,
        entrypoint=record.entrypoint,
        port=record.port,
        status=record.status,
        pid=record.pid,
        last_error=record.last_error,
    )
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/{server_id}/start", response_model=FastMCPServerResponse)
async def start_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        record = _fastmcp_manager.start_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = FastMCPServerResponse(
        id=record.id,
        server_name=record.server_name,
        namespace=record.namespace,
        version=record.version,
        install_method=record.install_method,
        repo_url=record.repo_url,
        entrypoint=record.entrypoint,
        port=record.port,
        status=record.status,
        pid=record.pid,
        last_error=record.last_error,
    )
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/{server_id}/stop", response_model=FastMCPServerResponse)
async def stop_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        record = _fastmcp_manager.stop_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FastMCPServerResponse(
        id=record.id,
        server_name=record.server_name,
        namespace=record.namespace,
        version=record.version,
        install_method=record.install_method,
        repo_url=record.repo_url,
        entrypoint=record.entrypoint,
        port=record.port,
        status=record.status,
        pid=record.pid,
        last_error=record.last_error,
    )


@router.delete("/servers/{server_id}")
async def delete_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> Dict[str, Any]:
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        _fastmcp_manager.delete_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, "fanout": await _fanout_fastmcp_reload()}
