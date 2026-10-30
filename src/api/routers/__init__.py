from .assistant import router as assistant_router
from .commands import router as commands_router
from .metrics import router as metrics_router
from .health import router as health_router

__all__ = [
    "assistant_router",
    "commands_router",
    "metrics_router",
    "health_router",
]
