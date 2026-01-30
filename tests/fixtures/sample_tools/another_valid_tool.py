"""Another valid sample tool for testing multiple tool loading."""

from pydantic import BaseModel, Field, ConfigDict

from app.registry import ToolDefinition, ToolRegistry


class AddInput(BaseModel):
    """Input for the add tool."""

    model_config = ConfigDict(extra="forbid")

    a: int = Field(description="First number")
    b: int = Field(description="Second number")


async def add_handler(payload: AddInput) -> int:
    """Handle the add tool."""
    return payload.a + payload.b


def register_tools(registry: ToolRegistry) -> None:
    """Register tools with the registry."""
    AddInput.model_rebuild(force=True)
    registry.register(
        ToolDefinition(
            name="add_numbers",
            description="Adds two numbers together.",
            input_model=AddInput,
            handler=add_handler,
        )
    )
