from fastmcp.tools import tool


@tool
def say_hello(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"
