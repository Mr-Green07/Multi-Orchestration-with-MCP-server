"""agent/classifier.py
====================
A tiny, deterministic intent classifier that runs *before* the model.

Why bother when the model can do it? Three reasons, all practical:

* **latency** - "how much disk is left" answers in under a millisecond instead of
  several seconds of prompt processing on a 4B model on CPU;
* **availability** - the read-only commands still work while the model loads, or on
  a machine where ``llama-cpp-python`` was never installed;
* **reliability** - the obvious phrasings are the ones a small model most often
  gets subtly wrong ("is my machine okay" -> ``machine_health`` with no arguments).

The classifier is intentionally conservative: it only fires on high-confidence
phrasings and returns ``None`` otherwise, in which case the planner is used. It
never matches anything destructive - power actions, kills and writes always go
through the model and the approval gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: (tool, arguments, matched-on phrases). Order matters: first match wins.
_RULES: list[tuple[str, dict[str, Any], tuple[str, ...]]] = [
    ("machine_health", {}, (
        "machine health", "system health", "health check", "how is my pc",
        "how is my computer", "how's my computer", "is my machine okay",
        "is my pc okay", "is my computer okay", "everything okay",
        "health snapshot", "status report",
    )),
    ("top_processes", {"sort": "cpu"}, (
        "what is using cpu", "what's using cpu", "cpu hogs", "top cpu",
        "busiest processes", "what is eating my cpu",
    )),
    ("top_processes", {"sort": "memory"}, (
        "what is using memory", "what's using memory", "ram hogs", "top memory",
        "busiest memory", "what is eating my ram",
    )),
    ("disk_inventory", {}, (
        "disk space", "how much space", "free space", "storage left",
        "all drives", "all volumes", "disk usage",
    )),
    ("network_status", {}, (
        "network status", "wifi status", "wi-fi status", "am i online",
        "connection status", "network speed",
    )),
    ("gpu_status", {}, (
        "gpu status", "graphics card", "is the gpu", "gpu usage", "vram",
    )),
    ("clipboard", {"action": "read"}, (
        "what did i copy", "read the clipboard", "read my clipboard",
        "what is on the clipboard", "what's on the clipboard",
    )),
    ("reminders", {"action": "list"}, (
        "my reminders", "list reminders", "pending reminders",
        "what am i forgetting",
    )),
    ("reminders", {"action": "due"}, (
        "anything due", "due reminders", "what is due",
    )),
    ("focus_mode", {"action": "status"}, (
        "am i in focus mode", "focus mode status", "is focus mode on",
    )),
    ("index_status", {}, (
        "what is indexed", "index status", "search index",
    )),
    ("system_inventory", {"kind": "apps"}, (
        "installed apps", "installed applications", "what programs are installed",
        "list apps",
    )),
    ("system_inventory", {"kind": "services"}, (
        "what services are running", "service status", "list services",
    )),
    ("system_inventory", {"kind": "startup"}, (
        "startup items", "what starts with windows", "startup programs",
        "autostart",
    )),
    ("system_inventory", {"kind": "errors"}, (
        "recent errors", "any errors", "event log", "system errors",
    )),
    ("system_inventory", {"kind": "windows"}, (
        "open windows", "what windows are open", "list windows",
    )),
]

#: A few parameterised forms, matched by regex.
_PATTERNS: list[tuple[re.Pattern[str], str, Any]] = [
    (re.compile(r"\b(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", re.I),
     "hardware_control", lambda m: {"target": "volume", "value": int(m.group(1))}),
    (re.compile(r"\bbrightness\s+(?:to\s+)?(\d{1,3})\s*%?", re.I),
     "hardware_control", lambda m: {"target": "brightness", "value": int(m.group(1))}),
    (re.compile(r"\b(?:mute|unmute)\b", re.I),
     "hardware_control", lambda m: {"target": "mute", "value": 1}),
    (re.compile(r"\bremind me in (\d{1,4}) ?(?:min|minutes|m)\b(?: (?:to|that|about) (.+))?",
                re.I),
     "reminders", lambda m: {"action": "add", "minutes": int(m.group(1)),
                             "text": (m.group(2) or "reminder").strip()}),
    (re.compile(r"\bremind me in (\d{1,3}) ?(?:hours?|h)\b(?: (?:to|that|about) (.+))?",
                re.I),
     "reminders", lambda m: {"action": "add", "minutes": int(m.group(1)) * 60,
                             "text": (m.group(2) or "reminder").strip()}),
    (re.compile(r"\bundo (?:the )?(?:last )?(?:change|volume|brightness)\b", re.I),
     "hardware_undo", lambda m: {}),
    (re.compile(r"\blast audit (?:log )?entries\b", re.I), "__audit__", lambda m: {}),
]


@dataclass
class Intent:
    """A high-confidence shortcut result."""

    tool: str
    arguments: dict[str, Any]
    matched: str
    confidence: float = 0.95

    def as_decision(self) -> dict[str, Any]:
        return {"action": "tool", "tool": self.tool, "arguments": self.arguments}


def classify(text: str) -> Intent | None:
    """Return an :class:`Intent` when the phrasing is unambiguous, else ``None``."""
    if not text or len(text) > 200:
        return None
    normalised = " ".join(text.lower().replace("’", "'").split())

    for pattern, tool, build in _PATTERNS:
        match = pattern.search(normalised)
        if match:
            return Intent(tool=tool, arguments=build(match), matched=match.group(0))

    for tool, arguments, phrases in _RULES:
        for phrase in phrases:
            if phrase in normalised:
                return Intent(tool=tool, arguments=dict(arguments), matched=phrase)
    return None
