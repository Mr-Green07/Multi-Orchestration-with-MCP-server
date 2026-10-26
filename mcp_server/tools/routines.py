"""mcp_server/tools/routines.py
=============================
Three everyday-life features that all lean on the same two guarantees:
nothing irreversible happens without a second phase, and everything the agent
changes can be inspected afterwards.

* ``reminders``   - persisted in SQLite, so they survive a restart;
* ``focus_mode``  - one action that quiets the machine (volume + optional DND);
* ``organize``    - *plans* a tidy-up of a folder and only moves files when the
  caller passes ``apply`` **and** a confirmation token for the plan.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import config
from mcp_server import policy
from mcp_server.security import create_confirmation_token, verify_and_consume_token
from mcp_server.tools._common import (
    JailViolation,
    is_text_file,
    resolve_in_jail,
    respond,
    simulate,
)
from mcp_server.tools.hardware_controls import control_hardware, read_hardware_state


# =========================================================================== reminders
def _db() -> sqlite3.Connection:
    path = Path(config.MEMORY_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            due_at REAL NOT NULL,
            created_at REAL NOT NULL,
            fired INTEGER NOT NULL DEFAULT 0,
            cancelled INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    now = time.time()
    due = float(row["due_at"])
    return {
        "id": row["id"],
        "text": row["text"],
        "due_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due)),
        "due_ts": due,
        "due_in_seconds": int(max(0, due - now)),
        "overdue": due <= now,
        "fired": bool(row["fired"]),
    }


def reminders(action: str = "list", text: str | None = None, minutes: int = 20,
              reminder_id: int | None = None,
              correlation_id: str | None = None) -> dict[str, Any]:
    """Add, list, cancel or collect due reminders (SQLite-backed)."""
    tool = "reminders"
    action = str(action or "list").strip().lower()
    arguments = {"action": action, "text": text, "minutes": minutes,
                 "reminder_id": reminder_id}

    with _db() as conn:
        if action == "add":
            if not text or not text.strip():
                return respond(tool=tool, action=action, status="error",
                               summary="A reminder needs some text.",
                               payload={"code": "missing_text", "retryable": False,
                                        "user_hint": "Say what to remind you about."},
                               arguments=arguments, correlation_id=correlation_id)
            if minutes <= 0 or minutes > 60 * 24 * 30:
                return respond(tool=tool, action=action, status="error",
                               summary="The delay must be between 1 minute and 30 days.",
                               payload={"code": "invalid_delay", "retryable": False,
                                        "user_hint": "Give a delay in minutes, e.g. 20."},
                               arguments=arguments, correlation_id=correlation_id)
            due_at = time.time() + minutes * 60
            cursor = conn.execute(
                "INSERT INTO reminders (text, due_at, created_at) VALUES (?, ?, ?)",
                (text.strip()[:500], due_at, time.time()),
            )
            row = conn.execute("SELECT * FROM reminders WHERE id = ?",
                               (cursor.lastrowid,)).fetchone()
            return respond(tool=tool, action=action, status="success",
                           summary=f"Reminder set for {minutes} minute(s) from now: "
                                   f"{text.strip()[:80]}",
                           payload={"reminder": _row_to_dict(row)},
                           arguments=arguments, correlation_id=correlation_id,
                           applied=True)

        if action == "list":
            rows = conn.execute(
                "SELECT * FROM reminders WHERE cancelled = 0 AND fired = 0 "
                "ORDER BY due_at LIMIT ?", (config.MAX_INVENTORY_ROWS,)
            ).fetchall()
            return respond(tool=tool, action=action, status="success",
                           summary=(f"{len(rows)} pending reminder(s)." if rows
                                    else "No pending reminders."),
                           payload={"reminders": [_row_to_dict(r) for r in rows]},
                           arguments=arguments, correlation_id=correlation_id,
                           applied=None)

        if action == "due":
            rows = conn.execute(
                "SELECT * FROM reminders WHERE cancelled = 0 AND fired = 0 "
                "AND due_at <= ? ORDER BY due_at LIMIT ?",
                (time.time(), config.MAX_INVENTORY_ROWS),
            ).fetchall()
            if rows:
                conn.executemany("UPDATE reminders SET fired = 1 WHERE id = ?",
                                 [(r["id"],) for r in rows])
            return respond(tool=tool, action=action, status="success",
                           summary=(f"{len(rows)} reminder(s) are due."
                                    if rows else "Nothing is due."),
                           payload={"reminders": [_row_to_dict(r) for r in rows]},
                           arguments=arguments, correlation_id=correlation_id,
                           applied=True if rows else None)

        if action == "cancel":
            if reminder_id is None:
                return respond(tool=tool, action=action, status="error",
                               summary="Cancelling needs a reminder_id (see action='list').",
                               payload={"code": "missing_id", "retryable": False},
                               arguments=arguments, correlation_id=correlation_id)
            cursor = conn.execute(
                "UPDATE reminders SET cancelled = 1 "
                "WHERE id = ? AND cancelled = 0 AND fired = 0", (reminder_id,))
            if cursor.rowcount == 0:
                return respond(tool=tool, action=action, status="error",
                               summary=f"No pending reminder with id {reminder_id}.",
                               payload={"code": "not_found", "retryable": False,
                                        "user_hint": "List reminders first."},
                               arguments=arguments, correlation_id=correlation_id)
            return respond(tool=tool, action=action, status="success",
                           summary=f"Reminder {reminder_id} cancelled.",
                           payload={"reminder_id": reminder_id},
                           arguments=arguments, correlation_id=correlation_id,
                           applied=True)

    return respond(tool=tool, action=action, status="error",
                   summary=f"Unknown reminders action '{action}'.",
                   payload={"code": "invalid_action", "retryable": False,
                            "user_hint": "Use add, list, due or cancel."},
                   arguments=arguments, correlation_id=correlation_id)


# =========================================================================== focus mode
_FOCUS_STATE: dict[str, Any] = {"active": False, "previous": None}


def focus_mode(action: str = "on", level: int = 25,
               correlation_id: str | None = None) -> dict[str, Any]:
    """Quiet the machine: lower the volume and mute notifications where possible.

    Reversible: ``action="off"`` restores the volume captured when focus started.
    """
    tool = "focus_mode"
    action = str(action or "on").strip().lower()
    arguments = {"action": action, "level": level}

    if action not in {"on", "off", "status"}:
        return respond(tool=tool, action=action, status="error",
                       summary=f"Unknown focus action '{action}'.",
                       payload={"code": "invalid_action", "retryable": False,
                                "user_hint": "Use on, off or status."},
                       arguments=arguments, correlation_id=correlation_id)

    if action == "status":
        return respond(tool=tool, action=action, status="success",
                       summary=("Focus mode is on." if _FOCUS_STATE["active"]
                                else "Focus mode is off."),
                       payload={"active": _FOCUS_STATE["active"],
                                "previous": _FOCUS_STATE["previous"]},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=None)

    if policy.dry_run_enabled():
        target = level if action == "on" else (_FOCUS_STATE["previous"] or {}).get("volume")
        return simulate(tool=tool, action=action,
                        summary=f"Focus mode would switch {action} "
                                f"(volume -> {target}).",
                        payload={"level": target}, arguments=arguments,
                        correlation_id=correlation_id)

    if action == "on":
        before = read_hardware_state()
        _FOCUS_STATE["previous"] = {
            "volume": (before.get("volume") or {}).get("value"),
            "mute": (before.get("mute") or {}).get("value"),
        }
        level = max(0, min(int(level), 100))
        result = control_hardware("volume", level)
        applied = result.get("status") == "success"
        dnd = _enable_do_not_disturb()
        _FOCUS_STATE["active"] = True
        return respond(tool=tool, action=action,
                       status="success" if applied else result.get("status", "error"),
                       summary=("Focus mode on: volume set to "
                                f"{level}{' and notifications silenced' if dnd else ''}."
                                if applied else result.get("summary", "Volume unchanged.")),
                       payload={"level": level, "volume": result.get("payload", {}),
                                "do_not_disturb": dnd,
                                "previous": _FOCUS_STATE["previous"]},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=applied, previous=_FOCUS_STATE["previous"])

    previous = (_FOCUS_STATE.get("previous") or {}).get("volume")
    if previous is None:
        return respond(tool=tool, action=action, status="error",
                       summary="Focus mode was not on, so there is nothing to restore.",
                       payload={"code": "not_active", "retryable": False},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=False)
    result = control_hardware("volume", int(previous))
    _disable_do_not_disturb()
    _FOCUS_STATE["active"] = False
    return respond(tool=tool, action=action, status="success",
                   summary=f"Focus mode off: volume restored to {previous}.",
                   payload={"level": previous, "volume": result.get("payload", {})},
                   arguments=arguments, correlation_id=correlation_id,
                   applied=result.get("status") == "success")


def _enable_do_not_disturb() -> bool:
    """Best-effort 'do not disturb'. Returns True when the desktop accepted it."""
    if policy.host_platform() == "windows":
        # Windows 11 exposes focus assist through a shell COM object; that is a
        # write to user settings, so it stays opt-in and reports failure honestly.
        return False
    rc, _, _ = _run(["gsettings", "set", "org.gnome.desktop.notifications",
                     "show-banners", "false"])
    return rc == 0


def _disable_do_not_disturb() -> bool:
    if policy.host_platform() == "windows":
        return False
    rc, _, _ = _run(["gsettings", "set", "org.gnome.desktop.notifications",
                     "show-banners", "true"])
    return rc == 0


def _run(argv: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    import subprocess

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, OSError):
        return 127, "", "binary not found"


# =========================================================================== organize
_GROUPS = {
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls",
                  ".xlsx", ".csv", ".ppt", ".pptx"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2"},
    "Installers": {".exe", ".msi", ".deb", ".rpm", ".appimage", ".dmg"},
    "Code": {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".sh", ".ps1", ".html",
             ".css", ".sql", ".toml"},
}


def _group_for(suffix: str) -> str:
    lowered = suffix.lower()
    for group, suffixes in _GROUPS.items():
        if lowered in suffixes:
            return group
    return "Other"


def organize(relative_path: str = "", apply: bool = False,
             confirmation_token: str | None = None,
             correlation_id: str | None = None) -> dict[str, Any]:
    """Plan (or, with a token, perform) a tidy-up of a folder inside the jail.

    The plan is always computed first. ``apply=True`` without a token returns
    ``requires_confirmation`` - a plan can be reviewed before it touches a file.
    Files are *moved*, never deleted.
    """
    tool = "organize"
    action = "apply" if apply else "plan"
    arguments = {"relative_path": relative_path, "apply": apply}
    try:
        root = resolve_in_jail(relative_path)
    except JailViolation as exc:
        return respond(tool=tool, action=action, status="error", summary=str(exc),
                       payload={"code": "jail_violation", "retryable": False},
                       arguments=arguments, correlation_id=correlation_id)
    if not root.exists() or not root.is_dir():
        return respond(tool=tool, action=action, status="error",
                       summary=f"'{relative_path or '.'}' is not a folder in the jail.",
                       payload={"code": "not_a_directory", "retryable": False},
                       arguments=arguments, correlation_id=correlation_id)

    plan: list[dict[str, str]] = []
    for entry in sorted(root.iterdir()):
        if len(plan) >= config.MAX_INVENTORY_ROWS:
            break
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if not (is_text_file(entry) or entry.suffix):
            continue
        group = _group_for(entry.suffix)
        plan.append({"from": entry.name, "to": f"{group}/{entry.name}", "group": group})

    if not plan:
        return respond(tool=tool, action=action, status="success",
                       summary="Nothing to organise in that folder.",
                       payload={"moves": [], "folder": relative_path or "."},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=False)

    summary = (f"{len(plan)} file(s) can be grouped into "
               f"{len({p['group'] for p in plan})} folder(s).")

    if not apply:
        return respond(tool=tool, action="plan", status="success",
                       summary=summary + " Nothing was moved (dry plan).",
                       payload={"moves": plan, "folder": relative_path or ".",
                                "requires_apply": True},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=False)

    if policy.dry_run_enabled():
        return simulate(tool=tool, action=action, summary=summary + " No file was moved.",
                        payload={"moves": plan}, arguments=arguments,
                        correlation_id=correlation_id)

    expected = f"organize:{relative_path or '.'}"
    if not confirmation_token:
        token = create_confirmation_token(expected, {"moves": len(plan)})
        return respond(tool=tool, action=action, status="requires_confirmation",
                       summary=f"{summary} Confirm to move them.",
                       payload={"moves": plan, "warning": "Files will be moved into "
                                f"sub-folders of '{relative_path or '.'}'."},
                       arguments=arguments, correlation_id=correlation_id,
                       confirmation_token=token, applied=False)
    if not verify_and_consume_token(confirmation_token, expected_action=expected):
        return respond(tool=tool, action=action, status="error",
                       summary="Invalid or expired confirmation token; nothing was moved.",
                       payload={"code": "bad_token", "retryable": False},
                       arguments=arguments, correlation_id=correlation_id,
                       applied=False)

    moved, failed = [], []
    for item in plan:
        source, target = root / item["from"], root / item["to"]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                failed.append({**item, "reason": "target_exists"})
                continue
            shutil.move(str(source), str(target))
            moved.append(item)
        except OSError as exc:
            failed.append({**item, "reason": str(exc)[:120]})

    return respond(tool=tool, action=action,
                   status="success" if moved else "error",
                   summary=f"Moved {len(moved)} file(s); {len(failed)} skipped.",
                   payload={"moved": moved, "failed": failed},
                   arguments=arguments, correlation_id=correlation_id,
                   applied=bool(moved))
