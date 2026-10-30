import threading
import time
from collections import defaultdict
from typing import Dict, Any

class MetricsCollector:
    """
    Lightweight, thread-safe in-memory metrics collector.
    Used for tracking API call counts, component latencies (STT, LLM, TTS), 
    and system performance without needing an external time-series database.
    """
    
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MetricsCollector, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        # Using a lock to ensure thread safety when modifying metrics
        self._data_lock = threading.Lock()
        
        # Counters for specific events (e.g. intent matches, wakeword triggers)
        self.counters: Dict[str, int] = defaultdict(int)
        
        # Latency tracking (stores a list of recent execution times in ms)
        self.latencies: Dict[str, list] = defaultdict(list)
        
        # Keep only the last N latency entries to prevent memory leaks
        self.max_latency_history = 100
        
        # Timestamp when the collector was initialized
        self.start_time = time.time()

    def increment(self, metric_name: str, amount: int = 1):
        """Increments a specific counter metric by the given amount."""
        with self._data_lock:
            self.counters[metric_name] += amount

    def record_latency(self, metric_name: str, duration_ms: float):
        """Records a latency execution time (in milliseconds) for a specific operation."""
        with self._data_lock:
            history = self.latencies[metric_name]
            history.append(duration_ms)
            if len(history) > self.max_latency_history:
                history.pop(0)

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Returns a dictionary of all current metrics, including calculated 
        averages for latencies. Useful for a /metrics API endpoint.
        """
        with self._data_lock:
            snapshot = {
                "uptime_seconds": round(time.time() - self.start_time, 2),
                "counters": dict(self.counters),
                "latencies_ms": {}
            }
            
            for name, history in self.latencies.items():
                if history:
                    snapshot["latencies_ms"][name] = {
                        "avg": round(sum(history) / len(history), 2),
                        "min": round(min(history), 2),
                        "max": round(max(history), 2),
                        "latest": round(history[-1], 2),
                        "samples": len(history)
                    }
                else:
                    snapshot["latencies_ms"][name] = None
                    
            return snapshot

    def clear(self):
        """Resets all collected metrics to zero."""
        with self._data_lock:
            self.counters.clear()
            self.latencies.clear()

# Global singleton instance for easy import across the project
metrics = MetricsCollector()
