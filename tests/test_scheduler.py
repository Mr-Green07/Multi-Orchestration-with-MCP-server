"""The foreground scheduler: due reminders and one health report per day."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from agent.scheduler import Scheduler


def _reminder(text: str, minutes_from_now: int, reminder_id: int = 1) -> dict:
    due = datetime(2026, 5, 4, 12, 0) + timedelta(minutes=minutes_from_now)
    return {"id": reminder_id, "text": text, "due_ts": due.timestamp()}


NOW = datetime(2026, 5, 4, 12, 0)


def test_due_reminders_become_actions():
    scheduler = Scheduler(report_at="23:59")
    actions = scheduler.tick([_reminder("stretch", -5), _reminder("later", 30, 2)], now=NOW)
    assert [a.kind for a in actions] == ["reminder"]
    assert "stretch" in actions[0].summary
    assert actions[0].arguments == {"reminder_id": 1}


def test_report_fires_once_per_day():
    scheduler = Scheduler(report_at="09:00")
    assert scheduler.report_due(NOW) is True
    assert scheduler.report_due(NOW) is False                 # already sent today
    assert scheduler.report_due(NOW + timedelta(days=1)) is True


def test_report_does_not_fire_before_its_time():
    scheduler = Scheduler(report_at="23:00")
    assert scheduler.report_due(NOW) is False
    scheduler.mark_reported(date(2026, 5, 4))
    assert scheduler.report_due(datetime(2026, 5, 5, 9, 0)) is False


def test_report_can_be_disabled():
    scheduler = Scheduler(report_at="09:00", report_enabled=False)
    assert scheduler.report_due(NOW) is False
    assert [a.kind for a in scheduler.tick([], now=NOW)] == []


def test_a_bad_report_time_disables_the_report():
    assert Scheduler(report_at="nineish").report_due(NOW) is False


def test_tick_combines_reminders_and_the_report():
    scheduler = Scheduler(report_at="09:00")
    actions = scheduler.tick([_reminder("stand up", -1)], now=NOW)
    assert {a.kind for a in actions} == {"reminder", "health_report"}
