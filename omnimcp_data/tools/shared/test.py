"""
test Tool

Description of what this tool does.
"""

from pydantic import BaseModel, Field, ConfigDict
from app.registry import ToolDefinition, ToolRegistry


class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_param: str = Field(
        ...,
        description="Example parameter. Adjust fields and descriptions."
    )


async def test_handler(payload: TestInput):
    return {
        "ok": True,
        "echo": payload.example_param,
    }


def register_tools(registry: ToolRegistry) -> None:
    TestInput.model_rebuild(force=True)

    registry.register(
        ToolDefinition(
            name="test",
            description="Short description of the tool.",
            input_model=TestInput,
            handler=test_handler,
        )
    )
