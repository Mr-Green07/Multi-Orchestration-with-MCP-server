import time
import logging
# pyrefly: ignore [missing-import]
from fastapi import Request
# pyrefly: ignore [missing-import]
from starlette.middleware.base import BaseHTTPMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to log every incoming request, its method, path, and how long it took to process.
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Pass the request down the chain
        response = await call_next(request)
        
        process_time = time.time() - start_time
        logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s")
        
        return response

class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware stub for handling simple API key authentication and rate limiting.
    """
    async def dispatch(self, request: Request, call_next):
        # Example of protecting endpoints (skipping docs/openapi)
        if request.url.path.startswith("/api/v1/"):
            # Auth Check Example:
            api_key = request.headers.get("X-API-Key")
            if not api_key or api_key != "dev-secret-key":
                logger.warning(f"Unauthorized access attempt to {request.url.path}")
                return JSONResponse(
                    status_code=401, 
                    content={"error": True, "message": "Unauthorized. Invalid or missing API key."}
                )
            
            # Rate limiting logic would go here using Redis or in-memory token buckets
            
        return await call_next(request)
