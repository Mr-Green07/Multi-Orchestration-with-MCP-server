"""Tiny in-process event bus: one thread-safe queue of Event dataclasses.

Components never call each other across threads -- the audio worker publishes
(wake / barge_in / speech_start / endpoint / timeout) and the main loop
consumes. This is what lets the audio thread never block on the brain.
"""
from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any


@dataclass
class Event:
    kind: str          # "wake" | "barge_in" | "speech_start" | "endpoint" | "timeout"
    payload: Any = None


class EventBus:
    def __init__(self) -> None:
        self._q: "Queue[Event]" = Queue()

    def publish(self, event: Event) -> None:
        self._q.put(event)

    def next(self, timeout: float | None = None) -> Event | None:
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None       # lets the main loop poll its stop flag
