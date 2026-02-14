from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.gateway import create_app


def main() -> None:
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
