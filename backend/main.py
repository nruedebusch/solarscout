from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .config import get_settings
    from .database import Database, DatabaseConnectionError, DatabaseQueryError
except ImportError:
    from config import get_settings
    from database import Database, DatabaseConnectionError, DatabaseQueryError


logger = logging.getLogger(__name__)
settings = get_settings()
database = Database(settings.database_url)
allow_all_origins = "*" in settings.cors_origins

app = FastAPI(
    title="SolarScout API",
    version="0.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all_origins else settings.cors_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    buffer_distance: int = Field(default=500, ge=0, le=2000)
    exclude_nature: bool = Field(default=True)
    min_area: float = Field(default=2.0, ge=0.1)
    max_grid_distance: int = Field(default=2000, ge=100, le=10000)


@app.on_event("startup")
async def startup_event() -> None:
    try:
        await database.connect()
    except DatabaseConnectionError:
        logger.exception("Initial database connection failed.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await database.disconnect()


@app.get("/health")
async def health_check() -> dict[str, str]:
    try:
        await database.ensure_connected()
        if not await database.ping():
            raise HTTPException(status_code=503, detail="Database unavailable.")
    except DatabaseConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        await database.ensure_connected()
        return await database.analyze_sites(
            buffer_distance=payload.buffer_distance,
            exclude_nature=payload.exclude_nature,
            min_area=payload.min_area,
            max_grid_distance=payload.max_grid_distance,
        )
    except DatabaseConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DatabaseQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
