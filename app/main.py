import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.database import close_db, engine

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Schema is managed by Alembic (`alembic upgrade head`), not created here.
    yield
    await close_db()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)


@app.get("/health", tags=["system"])
async def health() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        # Log the error type only: driver messages can include host names.
        logger.warning("Database health check failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
