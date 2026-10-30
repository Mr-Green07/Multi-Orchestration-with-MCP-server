# pyrefly: ignore [missing-import]
from fastapi import APIRouter
# pyrefly: ignore [missing-import]
from src.api.schemas import HealthResponse

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint to verify the API is running.
    Often used by load balancers or Docker to check container health.
    """
    return HealthResponse(status="healthy")
