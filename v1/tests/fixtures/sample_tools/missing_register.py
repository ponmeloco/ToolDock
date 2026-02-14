"""A tool file missing the required register_tools function."""

from pydantic import BaseModel, Field, ConfigDict

from app.registry import ToolDefinition


class SomeInput(BaseModel):
    """Input for some tool."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="Some value")


async def some_handler(payload: SomeInput) -> str:
    """Handle the tool."""
    return f"Got: {payload.value}"


# NOTE: Missing register_tools() function - this tool should not be loaded
