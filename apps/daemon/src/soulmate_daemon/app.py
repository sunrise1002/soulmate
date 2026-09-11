"""FastAPI composition root for the local Soulmate service."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict, cast

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from soulmate_storage_sqlite import Database, Repositories
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from soulmate_daemon import __version__
from soulmate_daemon.config import Settings
from soulmate_daemon.jobs import DurableJobWorker
from soulmate_daemon.system import DEFAULT_PROFILE_ID, ensure_installation


class AppState(TypedDict):
    settings: Settings
    database: Database
    repositories: Repositories
    installation_id: str


class HealthResponse(BaseModel):
    status: str
    database: str
    migration: str


class SystemInfoResponse(BaseModel):
    service: str
    version: str
    installation_id: str
    profile_id: str
    privacy_mode: str


def _state(app: FastAPI) -> AppState:
    return cast(AppState, app.state.runtime)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings.database_path)
        database.migrate()
        if database.session_factory is None:
            raise RuntimeError("Database session factory was not initialized.")
        repositories = Repositories(database.session_factory)
        installation_id = ensure_installation(repositories.system_metadata, repositories.profiles)
        app.state.runtime = AppState(
            settings=resolved_settings,
            database=database,
            repositories=repositories,
            installation_id=installation_id,
        )
        stop = asyncio.Event()
        worker = DurableJobWorker(repositories.jobs, {})
        worker_task = asyncio.create_task(worker.run(stop), name="soulmate-durable-worker")
        try:
            yield
        finally:
            stop.set()
            await worker_task
            if database.engine is not None:
                database.engine.dispose()

    app = FastAPI(
        title="Soulmate", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        runtime = _state(app)
        database = runtime["database"]
        try:
            if database.engine is None:
                raise RuntimeError("Database is not connected.")
            with database.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            migration = (
                "current" if database.current_revision() == database.head_revision() else "outdated"
            )
        except (RuntimeError, SQLAlchemyError) as exc:
            raise HTTPException(status_code=503, detail="Local storage is unavailable.") from exc
        status = "healthy" if migration == "current" else "degraded"
        return HealthResponse(status=status, database="available", migration=migration)

    @app.get("/v1/system/info", response_model=SystemInfoResponse)
    def system_info() -> SystemInfoResponse:
        runtime = _state(app)
        return SystemInfoResponse(
            service="soulmate-daemon",
            version=__version__,
            installation_id=runtime["installation_id"],
            profile_id=DEFAULT_PROFILE_ID,
            privacy_mode=runtime["settings"].privacy.mode,
        )

    return app
