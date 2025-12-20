from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ToolError(Exception):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details or {}}


class ToolNotFoundError(ToolError):
    def __init__(self, tool_name: str):
        super().__init__(code="tool_not_found", message=f"Unbekanntes Tool: {tool_name}", details={"tool": tool_name})


class ToolValidationError(ToolError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(code="validation_error", message=message, details=details)


class ToolUnauthorizedError(ToolError):
    def __init__(self, message: str = "Nicht autorisiert"):
        super().__init__(code="unauthorized", message=message, details={})


class ToolInternalError(ToolError):
    def __init__(self, message: str = "Interner Fehler", details: Optional[Dict[str, Any]] = None):
        super().__init__(code="internal_error", message=message, details=details)
