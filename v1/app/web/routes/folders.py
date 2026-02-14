"""
Folder/Namespace Management API Routes.

Provides endpoints for managing tool folders (namespaces).

Security:
- Path traversal prevention
- Strict namespace name validation
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import verify_token
from app.loader import discover_namespaces
from app.deps import ensure_venv, delete_venv

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/folders", tags=["folders"])

# Namespace name pattern: lowercase letter start, then lowercase/numbers/underscore/hyphen
# Minimum 2 chars, maximum 50 chars
NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,49}$")

# Reserved namespace names that cannot be created/deleted
RESERVED_NAMESPACES = {"shared", "external", "config", "cache", "tmp", "temp"}


class FolderCreateRequest(BaseModel):
    """Request to create a new folder/namespace."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_-]+$",
        description="Folder name (lowercase, starts with letter, min 2 chars)",
    )


class FolderInfo(BaseModel):
    """Information about a folder/namespace."""

    name: str
    endpoint: str
    tool_count: int
    tools: List[str]


class FolderListResponse(BaseModel):
    """Response for listing folders."""

    folders: List[FolderInfo]
    total: int


def _get_base_tools_dir() -> Path:
    """Get the base tools directory path."""
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    return Path(data_dir).resolve() / "tools"


def _validate_namespace(namespace: str) -> None:
    """Validate namespace name for safety."""
    if not namespace:
        raise HTTPException(status_code=400, detail="Namespace name is required")

    if not NAMESPACE_PATTERN.match(namespace):
        raise HTTPException(
            status_code=400,
            detail="Invalid namespace name. Must be 2-50 chars, start with lowercase letter, contain only lowercase letters/numbers/underscore/hyphen.",
        )

    # Check for path traversal attempts
    if ".." in namespace or "/" in namespace or "\\" in namespace:
        logger.warning(f"Path traversal attempt in namespace: {namespace}")
        raise HTTPException(status_code=400, detail="Invalid namespace name")


def _get_safe_folder_path(namespace: str) -> Path:
    """
    Get a safe folder path for a namespace.

    Validates namespace and ensures path is within base directory.
    """
    _validate_namespace(namespace)

    base_dir = _get_base_tools_dir()
    folder_path = (base_dir / namespace).resolve()

    # Ensure the resolved path is within the base directory
    if not str(folder_path).startswith(str(base_dir)):
        logger.warning(f"Path traversal attempt: {namespace} resolved to {folder_path}")
        raise HTTPException(status_code=400, detail="Invalid namespace")

    return folder_path


def _count_tools_in_folder(folder_path: Path) -> tuple[int, List[str]]:
    """Count tool files in a folder and return their names."""
    if not folder_path.exists():
        return 0, []

    tool_files = [
        f.stem
        for f in folder_path.glob("*.py")
        if f.is_file() and not f.name.startswith("_")
    ]
    return len(tool_files), sorted(tool_files)


def _safe_rmtree(path: Path, base_dir: Path) -> None:
    """Delete directory only when it is a child of base_dir."""
    resolved_path = path.resolve()
    resolved_base = base_dir.resolve()
    if resolved_path == resolved_base or resolved_base not in resolved_path.parents:
        raise RuntimeError(f"Refusing to delete path outside base directory: {resolved_path}")
    shutil.rmtree(resolved_path)


@router.get("", response_model=FolderListResponse)
async def list_folders(_: str = Depends(verify_token)) -> FolderListResponse:
    """
    List all available tool folders (namespaces).

    Each folder represents a namespace that can be accessed via /{namespace}/mcp.
    """
    tools_dir = _get_base_tools_dir()

    if not tools_dir.exists():
        return FolderListResponse(folders=[], total=0)

    namespaces = discover_namespaces(str(tools_dir))
    folders = []

    for ns in namespaces:
        try:
            folder_path = _get_safe_folder_path(ns)
            tool_count, tools = _count_tools_in_folder(folder_path)
            folders.append(
                FolderInfo(
                    name=ns,
                    endpoint=f"/{ns}/mcp",
                    tool_count=tool_count,
                    tools=tools,
                )
            )
        except HTTPException:
            # Skip invalid namespace names
            continue

    return FolderListResponse(folders=folders, total=len(folders))


@router.get("/{namespace}", response_model=FolderInfo)
async def get_folder(
    namespace: str,
    _: str = Depends(verify_token),
) -> FolderInfo:
    """
    Get information about a specific folder/namespace.
    """
    folder_path = _get_safe_folder_path(namespace)

    if not folder_path.exists() or not folder_path.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Namespace folder not found: {namespace}",
        )

    tool_count, tools = _count_tools_in_folder(folder_path)

    return FolderInfo(
        name=namespace,
        endpoint=f"/{namespace}/mcp",
        tool_count=tool_count,
        tools=tools,
    )


@router.post("", response_model=FolderInfo)
async def create_folder(
    request: FolderCreateRequest,
    _: str = Depends(verify_token),
) -> FolderInfo:
    """
    Create a new tool folder (namespace).

    The folder will be accessible via /{name}/mcp after tools are added.
    """
    # Additional validation
    if request.name.lower() in RESERVED_NAMESPACES:
        raise HTTPException(
            status_code=400,
            detail=f"'{request.name}' is a reserved name and cannot be used",
        )

    folder_path = _get_safe_folder_path(request.name)

    if folder_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Folder already exists: {request.name}",
        )

    try:
        folder_path.mkdir(parents=True, exist_ok=False)
        # Create namespace venv on folder creation
        ensure_venv(request.name)
        logger.info(f"Created folder: {folder_path}")

        return FolderInfo(
            name=request.name,
            endpoint=f"/{request.name}/mcp",
            tool_count=0,
            tools=[],
        )

    except Exception as e:
        # Roll back partially-created state to avoid namespace clutter.
        try:
            if folder_path.exists():
                _safe_rmtree(folder_path, _get_base_tools_dir())
        except Exception:
            logger.warning(f"Failed to rollback folder after create error: {folder_path}", exc_info=True)
        try:
            delete_venv(request.name)
        except Exception:
            logger.warning(f"Failed to rollback venv after create error: {request.name}", exc_info=True)
        logger.error(f"Failed to create folder {request.name}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create folder",
        )


@router.delete("/{namespace}")
async def delete_folder(
    namespace: str,
    force: bool = False,
    _: str = Depends(verify_token),
) -> dict:
    """
    Delete a tool folder (namespace).

    Args:
        namespace: The folder name to delete
        force: If True, delete even if folder contains tools
    """
    # Prevent deletion of reserved namespaces
    if namespace.lower() in RESERVED_NAMESPACES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete the '{namespace}' namespace (reserved)",
        )

    folder_path = _get_safe_folder_path(namespace)

    if not folder_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Folder not found: {namespace}",
        )

    tool_count, tools = _count_tools_in_folder(folder_path)

    if tool_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"Folder contains {tool_count} tools. Use force=true to delete anyway.",
        )

    try:
        _safe_rmtree(folder_path, _get_base_tools_dir())
        # Remove namespace venv on folder deletion
        delete_venv(namespace)
        logger.info(f"Deleted folder: {folder_path}")

        return {
            "success": True,
            "message": f"Deleted folder: {namespace}",
            "deleted_tools": tool_count,
        }

    except Exception as e:
        logger.error(f"Failed to delete folder {namespace}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete folder",
        )
