import time
import logging
from functools import wraps
from typing import Callable, Any

log = logging.getLogger(__name__)

def timed(func: Callable) -> Callable:
    """
    Decorator that logs the execution time of a function.
    Useful for profiling performance (e.g., ASR transcription, LLM generation).
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        
        duration = end_time - start_time
        # Use a more readable format for milliseconds if it's very fast
        if duration < 1.0:
            log.debug(f"{func.__name__} took {duration * 1000:.2f} ms to execute.")
        else:
            log.debug(f"{func.__name__} took {duration:.2f} s to execute.")
            
        return result
    return wrapper


def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0, exceptions: tuple = (Exception,)) -> Callable:
    """
    Decorator that retries a function if it raises specified exceptions.
    Useful for network calls (e.g., reaching the Ollama API) or hardware reads.
    
    :param max_retries: Maximum number of times to retry before failing.
    :param delay: Initial delay between retries in seconds.
    :param backoff: Multiplier for the delay after each retry.
    :param exceptions: Tuple of exception types to catch and retry on.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        log.error(f"Function {func.__name__} failed after {max_retries} retries. Final error: {e}")
                        raise
                    
                    log.warning(f"Function {func.__name__} failed with '{e}'. Retrying in {current_delay}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator


def cache_result(func: Callable) -> Callable:
    """
    Decorator that caches the result of a function based on its arguments.
    Useful for expensive local lookups or immutable parsing operations.
    Note: Arguments must be hashable (e.g., strings, tuples, ints, not dicts/lists).
    """
    cache = {}

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        # Create a hashable key out of args and kwargs
        # (kwargs items are sorted to ensure consistent hashing)
        key = (args, frozenset(sorted(kwargs.items())))
        
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        
        return cache[key]

    # Expose a method to clear the cache manually if needed
    wrapper.clear_cache = lambda: cache.clear()
    return wrapper
