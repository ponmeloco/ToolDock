"""A valid sample tool for testing."""

from pydantic import BaseModel, Field, ConfigDict

from app.registry import ToolDefinition, ToolRegistry


class GreetInput(BaseModel):
    """Input for the greet tool."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="World", description="Name to greet")


async def greet_handler(payload: GreetInput) -> str:
    """Handle the greet tool."""
    return f"Hello, {payload.name}!"


def register_tools(registry: ToolRegistry) -> None:
    """Register tools with the registry."""
    GreetInput.model_rebuild(force=True)
    registry.register(
        ToolDefinition(
            name="greet",
            description="Returns a greeting message.",
            input_model=GreetInput,
            handler=greet_handler,
        )
    )
