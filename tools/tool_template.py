"""
Tool Template

Copy this file into a domain directory under tools/, for example:
tools/shared/my_tool.py
"""

from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry


class MyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_param: str = Field(
        ...,
        description="Example parameter. Adjust fields and descriptions."
    )


async def my_tool_handler(payload: MyToolInput):
    return {
        "ok": True,
        "echo": payload.example_param,
    }


def register_tools(registry: ToolRegistry) -> None:
    MyToolInput.model_rebuild(force=True)

    registry.register(
        ToolDefinition(
            name="my_tool",
            description="Short description of the tool.",
            input_model=MyToolInput,
            handler=my_tool_handler,
        )
    )
