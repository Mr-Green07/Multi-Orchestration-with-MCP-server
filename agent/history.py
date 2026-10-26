"""agent/history.py
=================
Conversation memory for a model with a small context window.

Three constraints shape this file:

* a 4B model at ``n_ctx=2048`` cannot hold a long conversation, so the history is
  bounded twice - by number of turns *and* by characters;
* pronouns matter ("make it quieter" only resolves if the previous exchange is
  present), so the *most recent* turns are kept verbatim and older ones are folded
  into a one-line summary;
* the summary is extractive on purpose: no extra model call, no extra latency, and
  it is deterministic, so tests can assert on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import config


@dataclass
class Turn:
    """One completed request/response pair."""

    user: str
    assistant: str
    tools: list[str] = field(default_factory=list)

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "user", "content": self.user},
            {"role": "assistant", "content": self.assistant},
        ]

    def one_line(self, width: int = 120) -> str:
        tools = f" [{', '.join(self.tools)}]" if self.tools else ""
        return f"user: {self.user[:width]} -> assistant: {self.assistant[:width]}{tools}"


class ConversationMemory:
    """Bounded multi-turn memory: recent turns verbatim, older ones summarized."""

    def __init__(self, max_turns: int | None = None,
                 max_chars: int | None = None) -> None:
        self.max_turns = config.MEMORY_MAX_TURNS if max_turns is None else max_turns
        self.max_chars = config.MEMORY_MAX_CHARS if max_chars is None else max_chars
        self.turns: list[Turn] = []
        self.previous: list[Turn] = []       # evicted turns, summarised

    # ------------------------------------------------------------------ writing
    def add(self, user: str, assistant: str, tools: list[str] | None = None) -> None:
        self.turns.append(Turn(user=user.strip(), assistant=assistant.strip(),
                               tools=list(tools or [])))
        self._trim()

    def _trim(self) -> None:
        while len(self.turns) > self.max_turns:
            self.previous.append(self.turns.pop(0))
        while self._size() > self.max_chars and self.turns:
            self.previous.append(self.turns.pop(0))

    def _size(self) -> int:
        return sum(len(t.user) + len(t.assistant) for t in self.turns)

    # ------------------------------------------------------------------ reading
    def summary(self, width: int = 110) -> str:
        """Rolling summary of evicted turns (newest last, capped in length)."""
        if not self.previous:
            return ""
        lines = [turn.one_line(width) for turn in self.previous[-4:]]
        dropped = len(self.previous) - len(lines)
        prefix = f"({dropped} earlier turn(s) omitted) " if dropped > 0 else ""
        return prefix + " | ".join(lines)

    def messages(self) -> list[dict[str, str]]:
        """Verbatim recent turns, ready to append after the system prompt."""
        out: list[dict[str, str]] = []
        for turn in self.turns:
            out.extend(turn.as_messages())
        return out

    def context_note(self) -> str | None:
        """A short system-style note describing what came before, if anything."""
        summary = self.summary()
        if not summary:
            return None
        return f"CONVERSATION SO FAR (compressed)\n{summary}"

    def clear(self) -> None:
        self.turns.clear()
        self.previous.clear()

    def __len__(self) -> int:
        return len(self.turns)
