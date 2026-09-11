"""Empty application shell; product endpoints begin in Phase 1."""

from fastapi import FastAPI

from soulmate_daemon.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an inert application without storage or provider side effects."""
    app = FastAPI(title="Soulmate", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings if settings is not None else Settings()
    return app
