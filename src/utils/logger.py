import sys
import logging
from pathlib import Path
from loguru import logger

# Intercept standard library logging to route it through loguru
class InterceptHandler(logging.Handler):
    """
    Default handler from loguru documentation to intercept standard logging 
    messages and route them into the loguru sink.
    """
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_logger(log_level: str = "INFO"):
    """
    Configures loguru structured logging with console output and file rotation.
    
    :param log_level: The minimum log level to capture (e.g., "DEBUG", "INFO")
    """
    # Define the log directory based on the project structure (data/logs/)
    base_dir = Path(__file__).parent.parent.parent
    log_dir = base_dir / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file_path = log_dir / "asr_assistant.log"

    # Remove default loguru handler
    logger.remove()

    # 1. Console Sink: Colourful, readable logging for the terminal
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )

    # 2. File Sink: Structured logging with rotation and retention
    # Rotates the log file when it hits 10 MB, and keeps the last 5 files.
    logger.add(
        str(log_file_path),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",       # Rotate when file reaches 10 MB
        retention=5,            # Keep 5 backup log files
        compression="zip",      # Compress old logs to save space
        serialize=False,        # Set to True if you want JSON structured logs in the file
        enqueue=True            # Thread-safe writing (critical for our audio threads)
    )

    # Intercept the standard logging module
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    logger.debug("Loguru logging successfully configured.")

# Automatically setup the logger on import (with a default level)
# If you want to change the level based on .env later, call setup_logger("DEBUG") in main.py
setup_logger()
