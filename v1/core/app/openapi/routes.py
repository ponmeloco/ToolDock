from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.engine import NamespaceNotFound, ToolEngine, ToolNotFound
from app.workers.protocol import WorkerError


def create_router(engine: ToolEngine) -> APIRouter:
    router = APIRouter()

    @router.get("/tools")
    async def list_tools(x_namespace: str = Header(alias="X-Namespace")):
        try:
            return await engine.list_tools(x_namespace)
        except NamespaceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.get("/tools/{tool_name}/schema")
    async def tool_schema(tool_name: str, x_namespace: str = Header(alias="X-Namespace")):
        try:
            return await engine.get_schema(x_namespace, tool_name)
        except NamespaceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ToolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except WorkerError as exc:
            raise _worker_error_to_http(exc) from exc

    @router.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request, x_namespace: str = Header(alias="X-Namespace")):
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body") from exc

        if not isinstance(body, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Body must be an object")

        try:
            return await engine.call_tool(x_namespace, tool_name, body)
        except NamespaceNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ToolNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except WorkerError as exc:
            raise _worker_error_to_http(exc) from exc

    return router


def _worker_error_to_http(err: WorkerError) -> HTTPException:
    if err.code == "tool_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err.message)
    if err.code == "invalid_arguments":
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err.message)
    if err.code in {"execution_timeout", "worker_timeout"}:
        return HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=err.message)
    if err.code in {"worker_unavailable", "worker_crashed"}:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=err.message)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=err.message)
