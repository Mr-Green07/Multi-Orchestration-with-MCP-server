"""
This file imports all handlers so that when `src.tasks.handlers` is imported, 
the @TaskRegistry.register decorators are fired, properly registering 
all classes into the TaskRegistry router.
"""

from .audio_handler import AudioHandler
from .device_handler import DeviceHandler
from .system_handler import SystemHandler
from .time_handler import TimeHandler
from .knowledge_handler import KnowledgeHandler

# Explicitly export them so linters don't complain about unused imports
__all__ = [
    "AudioHandler",
    "DeviceHandler",
    "SystemHandler",
    "TimeHandler",
    "KnowledgeHandler"
]
