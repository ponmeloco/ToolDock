from pydantic import BaseModel, Field, ConfigDict

from app.registry import ToolDefinition, ToolRegistry


class HelloWorldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        description="Name to greet"
    )


async def hello_world_handler(payload: HelloWorldInput) -> str:
    user_name = payload.name or "World"
    return f"Hello, {user_name}! The tool server is functioning correctly."


def register_tools(registry: ToolRegistry) -> None:
    HelloWorldInput.model_rebuild(force=True)

    registry.register(
        ToolDefinition(
            name="hello_world",
            description="Returns a greeting. Useful to validate tool calling end to end.",
            input_model=HelloWorldInput,
            handler=hello_world_handler,
        )
    )
