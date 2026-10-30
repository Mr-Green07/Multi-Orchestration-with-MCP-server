"""Assistant finite-state machine.

  IDLE ──wake──► LISTENING ──endpoint──► THINKING ──answer──► SPEAKING ──played──► IDLE
                    │                     │   ▲                  │
                    │timeout              ▼   │observation       │barge-in
                    ▼                    ACTING (tool)           ▼
                   IDLE                                      LISTENING

Every transition in the system goes through transition(), which raises
InvalidTransition on anything not in the LEGAL table. This is deliberate:
a wiring bug (e.g. an endpoint arriving while IDLE) explodes loudly at the
exact line that's wrong, instead of corrupting state silently.
Components stay dumb -- only the pipeline calls transition().
"""
from __future__ import annotations

import logging
import threading
from enum import Enum, auto

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()       # only the wake-word engine is working (~1% CPU)
    LISTENING = auto()  # VAD endpointer active, collecting the utterance
    THINKING = auto()   # STT + LLM working on a reply
    ACTING = auto()     # a tool is executing (agent loop)
    SPEAKING = auto()   # TTS playback; wake engine in raised-threshold mode


class InvalidTransition(RuntimeError):
    pass


class StateMachine:
    LEGAL = {
        (State.IDLE, State.LISTENING),      # wake word
        (State.LISTENING, State.THINKING),  # endpoint: utterance captured
        (State.LISTENING, State.IDLE),      # no-speech timeout
        (State.THINKING, State.ACTING),     # agent invokes a tool
        (State.ACTING, State.THINKING),     # tool observation returned
        (State.THINKING, State.SPEAKING),   # answer starts streaming
        (State.THINKING, State.IDLE),       # error recovery
        (State.SPEAKING, State.IDLE),       # reply fully played
        (State.SPEAKING, State.LISTENING),  # barge-in
    }

    def __init__(self) -> None:
        self._state = State.IDLE
        self._lock = threading.Lock()
        self.on_change = None          # hook: (old, new) -> None  (logs, tests)

    @property
    def state(self) -> State:
        return self._state

    def transition(self, new: State) -> None:
        with self._lock:
            if (self._state, new) not in self.LEGAL:
                raise InvalidTransition(f"{self._state.name} -> {new.name}")
            old, self._state = self._state, new
        log.info("state: %s -> %s", old.name, new.name)
        if self.on_change is not None:
            self.on_change(old, new)
