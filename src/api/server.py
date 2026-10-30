import logging
# pyrefly: ignore [missing-import]
from fastapi import FastAPI
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.exceptions import RequestValidationError

# pyrefly: ignore [missing-import]
from src.api.middleware import RequestLoggingMiddleware, AuthRateLimitMiddleware
# pyrefly: ignore [missing-import]
from src.api.exceptions import custom_http_exception_handler, validation_exception_handler

logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    """
    Factory pattern to create and configure the FastAPI application.
    This ensures that when the app boots up, all middleware, CORS policies,
    and custom error handlers are properly attached.
    """
    app = FastAPI(
        title="Antigravity Voice Assistant API",
        description="REST API for remote STT, TTS, and NLU processing.",
        version="1.0.0"
    )

    # 1. Mount CORS Middleware (Crucial if a web frontend is going to call this API)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, replace "*" with your actual frontend URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Mount Custom Middlewares (Order matters! The last one added is the first one hit)
    app.add_middleware(AuthRateLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # 3. Mount Custom Exception Handlers
    app.add_exception_handler(Exception, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # 4. Mount Routers
    # pyrefly: ignore [missing-import]
    from src.api.routers import (
        assistant_router,
        commands_router,
        metrics_router,
        health_router
    )
    
    app.include_router(assistant_router, prefix="/api/v1", tags=["Voice"])
    app.include_router(commands_router, prefix="/api/v1", tags=["Text"])
    app.include_router(metrics_router, prefix="/api/v1", tags=["System"])
    app.include_router(health_router, tags=["System"])

    logger.info("FastAPI application created and configured.")
    return app
