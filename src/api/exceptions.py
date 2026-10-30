# pyrefly: ignore [missing-import]
from fastapi import Request
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse
# pyrefly: ignore [missing-import]
from fastapi.exceptions import RequestValiadationError
import logging

logger = logging.getLogger(__name__)

async def custom_http_exception_handler(request: Request, exc: Exception):
    
    logger.error(f"HTTP Error on {request.method} {request.url.path}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": "An internal server error occurred.", "details": str(exc)},
    )

async def validation_exception_handler(request: Request, exc: RequestValiadationError):
    """
    Handles Pydantic validation errors (e.g. missing fields in the JSON payload)
    """
    return JSONResponse(
        status_code=422,
        content={"error": True, "message": "Invalid request payload.", "details": exc.errors()},
    )
