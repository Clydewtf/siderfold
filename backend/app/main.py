from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.api.health import router as health_router
from app.api.internal.moderation import (
    register_internal_api_exception_handlers,
    router as internal_router,
)
from app.api.v1.catalog import register_read_api_exception_handlers, router as catalog_router
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(title=resolved_settings.app_name, version="0.8.0")
    application.state.settings = resolved_settings
    application.state.db_engine = engine or create_db_engine(resolved_settings)
    register_read_api_exception_handlers(application)
    register_internal_api_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(catalog_router)
    application.include_router(internal_router)
    return application


app = create_app()
