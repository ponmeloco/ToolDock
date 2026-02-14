from fastmcp.tools import tool


@tool
def to_upper(text: str) -> str:
    """Upper-case a string."""
    return text.upper()
