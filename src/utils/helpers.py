import json
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional

# Re-export retry from decorators since it's commonly thought of as a helper
from src.utils.decorators import retry

log = logging.getLogger(__name__)

def safe_read_json(filepath: Path | str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Safely reads a JSON file and returns its contents as a dictionary.
    If the file is missing or contains invalid JSON, it logs a warning and returns the default.
    """
    path = Path(filepath)
    if default is None:
        default = {}
        
    if not path.exists():
        log.warning(f"JSON file not found at {path}. Returning default.")
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {path}: {e}. Returning default.")
        return default
    except Exception as e:
        log.error(f"Error reading JSON from {path}: {e}. Returning default.")
        return default


def safe_read_yaml(filepath: Path | str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Safely reads a YAML file and returns its contents as a dictionary.
    If the file is missing or invalid, it logs a warning and returns the default.
    """
    path = Path(filepath)
    if default is None:
        default = {}
        
    if not path.exists():
        log.warning(f"YAML file not found at {path}. Returning default.")
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except yaml.YAMLError as e:
        log.error(f"Invalid YAML in {path}: {e}. Returning default.")
        return default
    except Exception as e:
        log.error(f"Error reading YAML from {path}: {e}. Returning default.")
        return default


def ensure_dir(dir_path: Path | str) -> Path:
    """
    Ensures that a directory exists, creating it and its parents if necessary.
    Returns the Path object of the directory.
    """
    path = Path(dir_path)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        log.debug(f"Created directory: {path}")
    return path

