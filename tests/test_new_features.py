"""New capability tests: inventory, reminders, focus, organise, memory, panic.

Every test here is host-neutral: the inventory tests accept ``success`` *or*
``unsupported`` because a CI container has no systemd, no desktop and no battery,
which is exactly the situation the tools are required to describe honestly rather
than crash on.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

import config
from agent.classifier import classify
from agent.history import ConversationMemory
from mcp_server import policy
from mcp_server.tools import routines, system_awareness


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(config, "BATTERY_GUARD_ENABLED", True)
    monkeypatch.setattr(config, "MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    policy.reset_all_limits()
    policy.set_panic(False)
    system_awareness.clear_cache()
    yield
    policy.reset_all_limits()
    policy.set_panic(False)
    system_awareness.clear_cache()


# --------------------------------------------------------------------- inventory
@pytest.mark.parametrize("kind", ["services", "startup", "apps", "errors", "windows"])
def test_inventory_never_raises_and_reports_a_contract(kind):
    result = system_awareness.system_inventory(kind)
    assert result["status"] in {"success", "unsupported"}
    assert result["metric_or_action"] == kind
    assert result["summary"]
    assert "payload" in result


def test_inventory_rejects_an_unknown_category():
    result = system_awareness.system_inventory("registry")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "invalid_category"
    assert result["payload"]["retryable"] is False


def test_inventory_is_cached_for_repeat_queries():
    first = system_awareness.system_inventory("apps")
    second = system_awareness.system_inventory("apps")
    assert first["status"] == second["status"]
    if first["status"] == "success":
        assert second["payload"].get("cached") is True


# --------------------------------------------------------------------- reminders
def test_reminder_round_trip():
    added = routines.reminders("add", text="drink water", minutes=30)
    assert added["status"] == "success" and added["applied"] is True
    reminder_id = added["payload"]["reminder"]["id"]

    listed = routines.reminders("list")
    assert listed["status"] == "success"
    assert [r["text"] for r in listed["payload"]["reminders"]] == ["drink water"]

    cancelled = routines.reminders("cancel", reminder_id=reminder_id)
    assert cancelled["status"] == "success"
    assert routines.reminders("list")["payload"]["reminders"] == []


def test_reminder_validation_and_unknown_id():
    assert routines.reminders("add", text="   ")["payload"]["code"] == "missing_text"
    assert routines.reminders("add", text="x", minutes=0)["payload"]["code"] == \
        "invalid_delay"
    assert routines.reminders("cancel", reminder_id=4242)["payload"]["code"] == "not_found"
    assert routines.reminders("nonsense")["payload"]["code"] == "invalid_action"


def test_due_reminders_are_collected_once():
    routines.reminders("add", text="overdue thing", minutes=1)
    # Backdate the row instead of sleeping.
    with sqlite3.connect(config.MEMORY_DB_PATH) as conn:
        conn.execute("UPDATE reminders SET due_at = ?", (time.time() - 5,))
    first = routines.reminders("due")
    assert first["status"] == "success"
    assert len(first["payload"]["reminders"]) == 1
    assert routines.reminders("due")["payload"]["reminders"] == []


# --------------------------------------------------------------------- focus mode
def test_focus_mode_status_reports_state():
    result = routines.focus_mode("status")
    assert result["status"] == "success"
    assert result["payload"]["active"] is False


def test_focus_mode_dry_run_touches_nothing(monkeypatch):
    monkeypatch.setattr(config, "DRY_RUN", True)
    result = routines.focus_mode("on", level=10)
    assert result["status"] == "dry_run"
    assert result["applied"] is False
    assert routines.focus_mode("status")["payload"]["active"] is False


def test_focus_mode_off_without_a_previous_state_is_an_error():
    result = routines.focus_mode("off")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "not_active"


# --------------------------------------------------------------------- organise
def test_organize_plans_without_moving_files(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", str(tmp_path))
    (tmp_path / "a.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "b.png").write_text("y", encoding="utf-8")

    plan = routines.organize("")
    assert plan["status"] == "success"
    moves = plan["payload"]["moves"]
    assert {m["to"] for m in moves} == {"Documents/a.pdf", "Images/b.png"}
    assert (tmp_path / "a.pdf").exists()          # a plan moves nothing


def test_organize_apply_requires_a_token(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", str(tmp_path))
    (tmp_path / "a.pdf").write_text("x", encoding="utf-8")

    first = routines.organize("", apply=True)
    assert first["status"] == "requires_confirmation"
    assert first["confirmation_token"]
    assert (tmp_path / "a.pdf").exists()

    bad = routines.organize("", apply=True, confirmation_token="nope")
    assert bad["status"] == "error"
    assert bad["payload"]["code"] == "bad_token"

    good = routines.organize("", apply=True,
                             confirmation_token=first["confirmation_token"])
    assert good["status"] == "success" and good["applied"] is True
    assert (tmp_path / "Documents" / "a.pdf").exists()


def test_organize_never_escapes_the_jail(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORKSPACE_JAIL_ROOT", str(tmp_path))
    result = routines.organize("../..")
    assert result["status"] == "error"
    assert result["payload"]["code"] == "jail_violation"


# --------------------------------------------------------------------- classifier
@pytest.mark.parametrize("text,tool", [
    ("how much disk space is left", "disk_inventory"),
    ("is my machine okay", "machine_health"),
    ("what's using cpu", "top_processes"),
    ("read my clipboard", "clipboard"),
    ("what is indexed", "index_status"),
    ("open windows", "system_inventory"),
])
def test_classifier_matches_obvious_read_only_requests(text, tool):
    intent = classify(text)
    assert intent is not None and intent.tool == tool


def test_classifier_extracts_parameters():
    assert classify("set the volume to 40") .arguments == {"target": "volume",
                                                           "value": 40}
    reminder = classify("remind me in 25 minutes to stretch")
    assert reminder.tool == "reminders"
    assert reminder.arguments == {"action": "add", "minutes": 25, "text": "stretch"}
    assert classify("remind me in 2 hours to call mum").arguments["minutes"] == 120


def test_classifier_stays_quiet_for_ambiguous_or_destructive_requests():
    for text in ["shut down the pc", "kill the chrome process", "hello there",
                 "delete my downloads folder", ""]:
        assert classify(text) is None


# --------------------------------------------------------------------- memory
def test_memory_keeps_recent_turns_and_summarises_older_ones():
    memory = ConversationMemory(max_turns=2)
    for index in range(4):
        memory.add(f"question {index}", f"answer {index}", ["machine_health"])
    assert len(memory) == 2
    assert memory.turns[-1].user == "question 3"
    summary = memory.summary()
    assert "question 0" in summary and "question 1" in summary
    assert memory.context_note().startswith("CONVERSATION SO FAR")


def test_memory_clear_and_empty_note():
    memory = ConversationMemory(max_turns=3)
    assert memory.context_note() is None
    memory.add("hi", "hello")
    memory.clear()
    assert len(memory) == 0 and memory.context_note() is None


def test_memory_respects_the_character_budget():
    memory = ConversationMemory(max_turns=10, max_chars=200)
    memory.add("a" * 150, "b" * 150)
    assert len(memory) == 0            # a single oversized turn is evicted, not kept
    assert memory.summary()


# --------------------------------------------------------------------- panic
def test_panic_blocks_destructive_tools_only():
    policy.set_panic(True, reason="test")
    with pytest.raises(policy.PanicActive):
        policy.assert_not_panicking("power_session")
    policy.assert_not_panicking("machine_health")     # read-only stays available
    policy.set_panic(False)
    policy.assert_not_panicking("power_session")


def test_battery_guard_refuses_heavy_tools_on_low_battery(monkeypatch):
    monkeypatch.setattr(policy, "battery_state",
                        lambda: {"available": True, "percent": 5.0,
                                 "plugged_in": False})
    refusal = policy.battery_guard("organize")
    assert refusal["code"] == "battery_low"
    assert policy.battery_guard("machine_health") is None      # cheap/read-only


def test_battery_guard_allows_plugged_in_machines(monkeypatch):
    monkeypatch.setattr(policy, "battery_state",
                        lambda: {"available": True, "percent": 5.0,
                                 "plugged_in": True})
    assert policy.battery_guard("organize") is None


def test_battery_guard_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "BATTERY_GUARD_ENABLED", False)
    monkeypatch.setattr(policy, "battery_state",
                        lambda: {"available": True, "percent": 1.0,
                                 "plugged_in": False})
    assert policy.battery_guard("organize") is None


# --------------------------------------------------------------------- capability card
def test_capability_card_is_plain_english_and_complete():
    from agent.capabilities import capability_card, card_dict

    card = capability_card(28)
    assert "WHAT I CAN TOUCH ON THIS MACHINE" in card
    assert "28 tools" in card
    for line in ("language model", "approval gates", "panic switch", "file access"):
        assert line in card
    data = card_dict(28)
    assert data["tool_count"] == 28
    assert set(data["capabilities"]) == {"brain", "hardware", "desktop", "awareness",
                                         "files", "safety"}
