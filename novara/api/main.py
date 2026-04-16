"""FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from novara.api.routers import admin, chapters, frontend, ingestion, works
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

# Static files — served at /static
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Jinja2 templates
_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "templates")
_templates = Jinja2Templates(directory=_TEMPLATES_DIR)
frontend.set_templates(_templates)

# CORS — wide open for development; lock down in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.novara_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — frontend routes first (no prefix) so / and /novel/{slug} resolve correctly
app.include_router(frontend.router)
app.include_router(works.router, prefix="/api/v1")
app.include_router(chapters.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return _templates.TemplateResponse(request, "404.html", {}, status_code=404)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
