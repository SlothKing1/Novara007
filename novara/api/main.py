"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from novara.api.routers import admin, chapters, ingestion, works
from novara.config import get_settings
from novara.ingestion.registry import autodiscover

log = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown."""
    log.info("novara_starting", env=settings.novara_env)
    # Register all source adapters
    autodiscover()
    log.info("adapters_registered", count=len(
        __import__("novara.ingestion.registry", fromlist=["list_adapters"]).list_adapters()
    ))
    yield
    log.info("novara_shutting_down")


app = FastAPI(
    title="Novara API",
    description=(
        "Multi-source web novel ingestion and serving platform. "
        "Handles works, versions, sources, chapters, metadata claims, and covers."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — wide open for development; lock down in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.novara_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(works.router, prefix="/api/v1")
app.include_router(chapters.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
