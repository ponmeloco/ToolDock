"""
Tool Management API Routes.

Provides endpoints for managing tools within namespaces.

Security:
- Path traversal prevention via strict path validation
- File type validation
- Content validation before save
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token
from app.web.validation import validate_tool_file, ValidationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/folders/{namespace}/tools", tags=["tools"])

# Allowed filename pattern: alphanumeric, underscores, hyphens, must end in .py
FILENAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*\.py$")


class ToolInfo(BaseModel):
    """Information about a tool file."""

    filename: str
    namespace: str
    path: str
    size: int


class ToolValidationResponse(BaseModel):
    """Response from tool validation."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    errors: List[str]
    warnings: List[str]
    info: dict


class ToolUploadResponse(BaseModel):
    """Response from tool upload."""

    success: bool
    message: str
    validation: ToolValidationResponse
    path: Optional[str] = None


class ToolUpdateRequest(BaseModel):
    """Request body for updating a tool."""

    model_config = ConfigDict(extra="forbid")

    content: str
    skip_validation: bool = False


class ToolListResponse(BaseModel):
    """Response for listing tools in a namespace."""

    namespace: str
    tools: List[ToolInfo]
    total: int


def _get_base_tools_dir() -> Path:
    """Get the base tools directory path."""
    data_dir = os.getenv("DATA_DIR", "omnimcp_data")
    return Path(data_dir).resolve() / "tools"


def _get_tools_dir(namespace: str) -> Path:
    """Get the tools directory path for a namespace with validation."""
    base_dir = _get_base_tools_dir()

    # Validate namespace name (prevent path traversal)
    if not re.match(r"^[a-z][a-z0-9_-]*$", namespace):
        raise HTTPException(
            status_code=400,
            detail="Invalid namespace name. Use lowercase letters, numbers, underscores, hyphens.",
        )

    tools_dir = (base_dir / namespace).resolve()

    # Ensure the resolved path is within the base directory
    if not str(tools_dir).startswith(str(base_dir)):
        logger.warning(f"Path traversal attempt detected: {namespace}")
        raise HTTPException(status_code=400, detail="Invalid namespace")

    return tools_dir


def _validate_filename(filename: str) -> None:
    """Validate filename to prevent path traversal and ensure safety."""
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Check for path traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        logger.warning(f"Path traversal attempt in filename: {filename}")
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check filename pattern
    if not FILENAME_PATTERN.match(filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename. Must start with a letter, contain only alphanumeric/underscore/hyphen, and end with .py",
        )


def _safe_file_path(tools_dir: Path, filename: str) -> Path:
    """
    Create a safe file path within the tools directory.

    Validates that the resolved path is within the expected directory.
    """
    _validate_filename(filename)

    file_path = (tools_dir / filename).resolve()

    # Ensure file path is within tools_dir
    if not str(file_path).startswith(str(tools_dir.resolve())):
        logger.warning(f"Path traversal attempt: {filename} resolved to {file_path}")
        raise HTTPException(status_code=400, detail="Invalid file path")

    return file_path


@router.get("", response_model=ToolListResponse)
async def list_tools(
    namespace: str,
    _: str = Depends(verify_token),
) -> ToolListResponse:
    """
    List all tool files in a namespace.

    Args:
        namespace: The namespace/folder name
    """
    tools_dir = _get_tools_dir(namespace)

    if not tools_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Namespace not found: {namespace}",
        )

    tools = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.is_file() and not py_file.name.startswith("_"):
            # Only include files that match our pattern
            if FILENAME_PATTERN.match(py_file.name):
                tools.append(
                    ToolInfo(
                        filename=py_file.name,
                        namespace=namespace,
                        path=f"/api/folders/{namespace}/tools/{py_file.name}",
                        size=py_file.stat().st_size,
                    )
                )

    return ToolListResponse(
        namespace=namespace,
        tools=tools,
        total=len(tools),
    )


class CreateToolRequest(BaseModel):
    """Request body for creating a new tool from template."""

    model_config = ConfigDict(extra="forbid")

    name: str


# Tool template content
TOOL_TEMPLATE = '''"""
{name} Tool

Description of what this tool does.
"""

from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry


class {class_name}Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_param: str = Field(
        ...,
        description="Example parameter. Adjust fields and descriptions."
    )


async def {handler_name}_handler(payload: {class_name}Input):
    return {{
        "ok": True,
        "echo": payload.example_param,
    }}


def register_tools(registry: ToolRegistry) -> None:
    {class_name}Input.model_rebuild(force=True)

    registry.register(
        ToolDefinition(
            name="{name}",
            description="Short description of the tool.",
            input_model={class_name}Input,
            handler={handler_name}_handler,
        )
    )
'''


@router.post("/create-from-template")
async def create_tool_from_template(
    namespace: str,
    request: CreateToolRequest,
    _: str = Depends(verify_token),
) -> dict:
    """
    Create a new tool from the template.

    Args:
        namespace: The namespace/folder name
        request: The tool name
    """
    tools_dir = _get_tools_dir(namespace)

    if not tools_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Namespace not found: {namespace}",
        )

    # Validate the name (should be snake_case)
    name = request.name.strip()
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise HTTPException(
            status_code=400,
            detail="Tool name must be snake_case (lowercase letters, numbers, underscores, start with letter)",
        )

    filename = f"{name}.py"
    file_path = tools_dir / filename

    if file_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Tool already exists: {filename}",
        )

    # Generate class name from snake_case (e.g., my_tool -> MyTool)
    class_name = "".join(word.capitalize() for word in name.split("_"))

    # Generate content from template
    content = TOOL_TEMPLATE.format(
        name=name,
        class_name=class_name,
        handler_name=name,
    )

    try:
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Created tool from template: {namespace}/{filename}")

        return {
            "success": True,
            "message": f"Tool created: {namespace}/{filename}",
            "filename": filename,
            "path": f"/api/folders/{namespace}/tools/{filename}",
        }

    except Exception as e:
        logger.error(f"Failed to create tool {namespace}/{filename}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create tool file",
        )


@router.get("/{filename}")
async def get_tool(
    namespace: str,
    filename: str,
    _: str = Depends(verify_token),
) -> dict:
    """
    Get a tool file's content and metadata.

    Args:
        namespace: The namespace/folder name
        filename: The tool filename (e.g., 'my_tool.py')
    """
    tools_dir = _get_tools_dir(namespace)
    file_path = _safe_file_path(tools_dir, filename)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {namespace}/{filename}",
        )

    try:
        content = file_path.read_text(encoding="utf-8")

        # Validate the file
        validation = validate_tool_file(content, filename)

        return {
            "filename": filename,
            "namespace": namespace,
            "size": file_path.stat().st_size,
            "content": content,
            "validation": {
                "is_valid": validation.is_valid,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "info": validation.info,
            },
        }

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File is not valid UTF-8 text",
        )
    except Exception as e:
        logger.error(f"Failed to read tool {namespace}/{filename}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to read tool file",
        )


@router.put("/{filename}")
async def update_tool(
    namespace: str,
    filename: str,
    request: ToolUpdateRequest,
    _: str = Depends(verify_token),
) -> dict:
    """
    Update a tool file's content.

    Args:
        namespace: The namespace/folder name
        filename: The tool filename (e.g., 'my_tool.py')
        request: The update request with new content
    """
    tools_dir = _get_tools_dir(namespace)
    file_path = _safe_file_path(tools_dir, filename)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {namespace}/{filename}",
        )

    # Limit content size (1MB max)
    if len(request.content.encode("utf-8")) > 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Content too large. Maximum size is 1MB.",
        )

    # Validate the new content
    validation = validate_tool_file(request.content, filename)

    if not validation.is_valid and not request.skip_validation:
        return {
            "success": False,
            "message": "Validation failed. Fix errors or set skip_validation=true.",
            "validation": {
                "is_valid": validation.is_valid,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "info": validation.info,
            },
        }

    # Save the updated content
    try:
        file_path.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated tool: {namespace}/{filename}")

        return {
            "success": True,
            "message": f"Tool updated: {namespace}/{filename}",
            "validation": {
                "is_valid": validation.is_valid,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "info": validation.info,
            },
        }

    except Exception as e:
        logger.error(f"Failed to update tool {namespace}/{filename}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to update tool file",
        )


@router.post("", response_model=ToolUploadResponse)
async def upload_tool(
    namespace: str,
    file: UploadFile = File(...),
    skip_validation: bool = False,
    _: str = Depends(verify_token),
) -> ToolUploadResponse:
    """
    Upload a tool file to a namespace.

    The file is validated before being saved (unless skip_validation=True).

    Args:
        namespace: The namespace/folder to upload to
        file: The Python file to upload
        skip_validation: If True, skip validation (not recommended)
    """
    tools_dir = _get_tools_dir(namespace)

    # Ensure namespace exists
    if not tools_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Namespace not found: {namespace}. Create it first via POST /api/folders",
        )

    # Validate filename
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Get safe file path (validates filename)
    file_path = _safe_file_path(tools_dir, file.filename)

    # Read content
    try:
        content = await file.read()
        content_str = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File must be valid UTF-8 encoded text",
        )

    # Limit file size (1MB max)
    if len(content) > 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size is 1MB.",
        )

    # Validate
    validation = validate_tool_file(content_str, file.filename)

    validation_response = ToolValidationResponse(
        is_valid=validation.is_valid,
        errors=validation.errors,
        warnings=validation.warnings,
        info=validation.info,
    )

    if not validation.is_valid and not skip_validation:
        return ToolUploadResponse(
            success=False,
            message="Validation failed. Fix errors or use skip_validation=true.",
            validation=validation_response,
            path=None,
        )

    # Save file
    try:
        file_path.write_text(content_str, encoding="utf-8")
        logger.info(f"Uploaded tool: {namespace}/{file.filename}")

        return ToolUploadResponse(
            success=True,
            message=f"Tool uploaded to {namespace}/{file.filename}",
            validation=validation_response,
            path=f"/api/folders/{namespace}/tools/{file.filename}",
        )

    except Exception as e:
        logger.error(f"Failed to save tool {namespace}/{file.filename}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to save tool file",
        )


@router.post("/validate", response_model=ToolValidationResponse)
async def validate_tool(
    namespace: str,
    file: UploadFile = File(...),
    _: str = Depends(verify_token),
) -> ToolValidationResponse:
    """
    Validate a tool file without saving it.

    Args:
        namespace: The namespace context (for logging)
        file: The Python file to validate
    """
    # Read content
    try:
        content = await file.read()
        content_str = content.decode("utf-8")
    except UnicodeDecodeError:
        return ToolValidationResponse(
            is_valid=False,
            errors=["File must be valid UTF-8 encoded text"],
            warnings=[],
            info={},
        )

    # Limit file size for validation too
    if len(content) > 1024 * 1024:
        return ToolValidationResponse(
            is_valid=False,
            errors=["File too large. Maximum size is 1MB."],
            warnings=[],
            info={},
        )

    validation = validate_tool_file(content_str, file.filename or "tool.py")

    return ToolValidationResponse(
        is_valid=validation.is_valid,
        errors=validation.errors,
        warnings=validation.warnings,
        info=validation.info,
    )


@router.delete("/{filename}")
async def delete_tool(
    namespace: str,
    filename: str,
    _: str = Depends(verify_token),
) -> dict:
    """
    Delete a tool file.

    Args:
        namespace: The namespace/folder name
        filename: The tool filename to delete
    """
    tools_dir = _get_tools_dir(namespace)
    file_path = _safe_file_path(tools_dir, filename)

    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {namespace}/{filename}",
        )

    try:
        file_path.unlink()
        logger.info(f"Deleted tool: {namespace}/{filename}")

        return {
            "success": True,
            "message": f"Deleted tool: {namespace}/{filename}",
        }

    except Exception as e:
        logger.error(f"Failed to delete tool {namespace}/{filename}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete tool file",
        )
