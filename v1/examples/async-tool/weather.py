import os

import httpx
from fastmcp.tools import tool


@tool
async def get_weather(city: str, units: str = "metric") -> dict:
    """Get current weather for a city."""
    api_key = os.environ["WEATHER_API_KEY"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "units": units, "appid": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "city": data["name"],
        "temperature": data["main"]["temp"],
        "description": data["weather"][0]["description"],
    }
