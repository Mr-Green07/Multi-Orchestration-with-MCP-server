"""agent/scheduler.py
===================
"Scheduled runs" without a service, a cron entry or a background daemon.

``python -m agent watch`` runs a plain foreground loop: every tick it asks the
reminders table what is due, and at a configured time of day it produces a health
report. The loop is deliberately dumb:

* no threads, so ``Ctrl+C`` stops it instantly;
* the *decision* of what is due lives in :class:`Scheduler`, which is pure apart
  from the clock it is handed, so the whole thing is testable without sleeping;
* it only ever calls read-only tools plus ``notify``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ScheduledAction:
    """One thing the loop should do now."""

    kind: str                       # reminder | health_report
    summary: str
    arguments: dict = field(default_factory=dict)


class Scheduler:
    """Decides what is due; the caller performs the actions."""

    def __init__(self, report_at: str | None = "09:00",
                 report_enabled: bool = True) -> None:
        self.report_at = report_at or ""
        self.report_enabled = report_enabled and bool(report_at)
        self._last_report_day: date | None = None

    # ------------------------------------------------------------------ report
    @staticmethod
    def _parse_time(value: str) -> tuple[int, int] | None:
        try:
            hour, _, minute = value.partition(":")
            return int(hour), int(minute)
        except (TypeError, ValueError):
            return None

    def report_due(self, now: datetime | None = None) -> bool:
        """True once per day, at or after the configured time."""
        if not self.report_enabled:
            return False
        parsed = self._parse_time(self.report_at)
        if parsed is None:
            return False
        now = now or datetime.now()
        if (now.hour, now.minute) < parsed:
            return False
        if self._last_report_day == now.date():
            return False
        self._last_report_day = now.date()
        return True

    def mark_reported(self, day: date | None = None) -> None:
        self._last_report_day = day or datetime.now().date()

    # ------------------------------------------------------------------ tick
    def tick(self, pending: list[dict], now: datetime | None = None) -> list[ScheduledAction]:
        """Turn the pending reminder rows plus the clock into actions."""
        now = now or datetime.now()
        actions: list[ScheduledAction] = []
        timestamp = now.timestamp()
        for reminder in pending:
            due_at = reminder.get("due_ts")
            if due_at is None:
                continue
            if float(due_at) <= timestamp:
                actions.append(ScheduledAction(
                    kind="reminder",
                    summary=f"Reminder: {reminder.get('text', '')}",
                    arguments={"reminder_id": reminder.get("id")},
                ))
        if self.report_due(now):
            actions.append(ScheduledAction(
                kind="health_report",
                summary=f"Daily health report ({self.report_at})",
            ))
        return actions

    # ------------------------------------------------------------------ sleep
    @staticmethod
    def sleep(seconds: float) -> None:
        """Indirection so tests (and Ctrl+C) never wait for a real minute."""
        time.sleep(seconds)
