"""agent/cli.py
============
The single entry point: ``python -m agent``.

Two ways to use it, deliberately:

* **conversation** - plain language goes to the planner, which picks tools;
* **direct** - slash commands call one tool immediately, no model involved.

The second matters: read-only work (``/health``, ``/top``, ``/tools``) stays
usable on a machine where the model is missing or still loading, and it is how the
user verifies each capability from ``start.md``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from collections.abc import Iterable
from typing import Any

import config
from agent import doctor as doctor_module
from agent.capabilities import capability_card
from agent.llm import LLMUnavailable, ScriptedLLM, load_default_llm
from agent.orchestrator import AgentResult, Orchestrator
from mcp_server import audit, policy

BANNER = "System Operator Agent"
HELP = """commands
  /help                 this help
  /tools                list tools published by the MCP server
  /health               machine health snapshot (direct, no model)
  /top [mem|cpu]        busiest processes
  /disk                 every volume and its usage
  /net                  network interfaces and throughput
  /gpu                  GPU status
  /clip [text]          read the clipboard, or copy TEXT
  /open <path|url>      open a workspace file or a URL
  /notify <text>        desktop notification
  /media <action>       play_pause | next | previous | stop
  /volume <0-100>       set volume (verified)
  /brightness <0-100>   set brightness (verified)
  /undo                 revert the last hardware change
  /search <query>       search the workspace jail
  /read <path>          read a file from the jail
  /write <path> <text>  write a file into the jail
  /remember k = v       store a fact
  /recall [query]       look up stored facts
  /macro list           saved routines
  /macro run <name>     replay a routine
  /capabilities         what this host can and cannot do, in plain English
  /inventory <kind>     services | startup | apps | errors | windows
  /remind <min> <text>  set a reminder
  /reminders            list pending reminders
  /focus [on|off]       quiet mode: volume down (+ DND where supported)
  /organize [path]      plan a tidy-up of a jail folder (nothing moves!)
  /history              recent conversation turns
  /clear                forget the conversation
  /panic                block every action right now (also Ctrl+C mid-request)
  /resume               release the panic switch
  /dry [on|off]         toggle dry-run mode
  /log [n]              recent audit records
  /jail                 show the workspace root
  /quit                 exit

commands (shell)
  python -m agent                  conversation (this REPL)
  python -m agent run --once TEXT  one request, then exit
  python -m agent run --script F   replay scripted model replies (no model needed)
  python -m agent watch            foreground scheduler: reminders + daily report
  python -m agent doctor           environment check
  python -m agent tools            list the published tools
  python -m agent selftest         model-free acceptance checks

anything else is sent to the model as a normal request."""


# --------------------------------------------------------------------------- helpers
def _icon(status: str) -> str:
    return {
        "success": "+", "ok": "+", "dry_run": "~", "requires_confirmation": "!",
        "cancelled": "-", "error": "x", "rate_limited": "!", "unsupported": "?",
        "needs_input": "?", "pending_approval": "!",
    }.get(status, ".")


def format_result(result: dict[str, Any], show_payload: bool = False) -> str:
    status = str(result.get("status", "?"))
    lines = [f"{_icon(status)} [{status}] {result.get('summary', '')}"]
    applied = result.get("applied")
    if applied is not None and status == "success":
        lines.append(f"  verified: {'yes' if applied else 'no'}")
    payload = result.get("payload") or {}
    if show_payload:
        body = json.dumps(payload, indent=2, default=str)
        lines.extend("  " + line for line in body.splitlines()[:40])
    elif payload.get("hint"):
        lines.append(f"  hint: {payload['hint']}")
    return "\n".join(lines)


def format_agent_result(result: AgentResult, show_payload: bool = False) -> str:
    if result.status == "needs_input" and result.question:
        return f"? {result.question}"
    lines = [f"{_icon(result.status)} {result.answer}"]
    for call in result.tool_calls:
        lines.append(f"  - {call.tool}({json.dumps(call.arguments, default=str)}) "
                     f"-> {call.status} in {call.duration_ms:.0f} ms")
    if show_payload:
        lines.append(f"  correlation: {result.correlation_id}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- approvals
def console_approval(info: dict[str, Any]) -> bool:
    """Interactive approval for a destructive action."""
    print("\n  SECURITY GATE - destructive action requested")
    print(f"    action : {info.get('tool')}")
    print(f"    args   : {json.dumps(info.get('arguments', {}), default=str)}")
    print(f"    effect : {info.get('summary', '')}")
    if info.get("warning"):
        print(f"    warning: {info['warning']}")
    print(f"    token  : {info.get('token')}  (single use, expires in "
          f"{config.CONFIRMATION_TTL_SECONDS} s)")
    try:
        answer = input("  Approve this action? [y/N]: ").strip().lower()
    except EOFError:
        answer = "n"
    return answer in {"y", "yes"}


def auto_decline(info: dict[str, Any]) -> bool:
    print(f"  ! approval required for {info.get('tool')}; declined automatically "
          f"(non-interactive session)")
    return False


# --------------------------------------------------------------------------- direct calls
class DirectClient:
    """Small helper that opens one MCP client per call (stateless, predictable)."""

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict:
        from fastmcp import Client

        from mcp_server.server import mcp

        async with Client(mcp) as client:
            result = await client.call_tool(tool, arguments or {})
            data = getattr(result, "data", result)
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and data:
                return data[0] if isinstance(data[0], dict) else {"status": "error",
                                                                 "summary": str(data)}
            return {"status": "error", "summary": f"unexpected response: {data!r}"}


# --------------------------------------------------------------------------- REPL
class Session:
    def __init__(self, llm=None, dry_run: bool | None = None, show_payload: bool = False,
                 interactive: bool = True) -> None:
        self.direct = DirectClient()
        self.show_payload = show_payload
        self.interactive = interactive
        self.llm = llm
        self.orchestrator = Orchestrator(
            llm=llm or _MissingModel(),
            approve=console_approval if interactive else auto_decline,
            on_event=self._on_event,
            dry_run=dry_run,
        )
        if dry_run is not None:
            policy.set_dry_run(dry_run)

    # ------------------------------------------------------------------ events
    def _on_event(self, event: str, fields: dict[str, Any]) -> None:
        if not self.interactive:
            return
        if event == "thinking":
            print(f"  .. thinking (step {fields.get('step', 1)}) ...", flush=True)
        elif event == "call":
            print(f"  .. {fields.get('tool')}({json.dumps(fields.get('arguments', {}), default=str)})")
        elif event == "result":
            print(f"  .. {fields.get('tool')} -> {fields.get('status')} "
                  f"({fields.get('duration_ms', 0):.0f} ms)")
        elif event == "classifier":
            print(f"  .. recognised as {fields.get('tool')} ('{fields.get('matched')}') "
                  f"- no model needed")
        elif event == "clarify":
            print(f"  ?? {fields.get('question')}")
        elif event == "repair":
            print(f"  .. retrying after: {fields.get('error')}")

    # ------------------------------------------------------------------ commands
    async def handle(self, line: str) -> bool:
        """Handle one input line. Returns False to exit."""
        text = line.strip()
        if not text:
            return True

        if text.startswith("/"):
            command, _, rest = text[1:].partition(" ")
            rest = rest.strip()
            if command in {"quit", "exit", "q"}:
                return False
            await self._slash(command, rest)
            return True

        # natural language -> planner
        try:
            result = await self.orchestrator.run(text)
            print(format_agent_result(result, self.show_payload))
        except LLMUnavailable as exc:
            print(f"x {exc}")
            print("  Read-only commands still work: /health /top /tools /search")
        except Exception as exc:
            print(f"x {type(exc).__name__}: {exc}")
            if self.show_payload:
                traceback.print_exc()
        return True

    async def _slash(self, command: str, rest: str) -> None:
        direct = self.direct
        if command == "help":
            print(HELP)
        elif command == "tools":
            from fastmcp import Client

            from mcp_server.server import mcp

            async with Client(mcp) as client:
                tools = await client.list_tools()
            for tool in tools:
                flags = []
                annotations = getattr(tool, "annotations", None)
                if annotations is not None:
                    if getattr(annotations, "readOnlyHint", False):
                        flags.append("read-only")
                    if getattr(annotations, "destructiveHint", False):
                        flags.append("destructive")
                print(f"  {tool.name:<18} {', '.join(flags) or 'writes'}")
        elif command == "health":
            print(format_result(await direct.call("machine_health"), self.show_payload))
        elif command == "top":
            sort = rest if rest in {"cpu", "mem", "memory"} else "memory"
            print(format_result(await direct.call("top_processes",
                                                  {"limit": 8, "sort": "cpu" if sort == "cpu" else "memory"}),
                                self.show_payload))
        elif command == "disk":
            print(format_result(await direct.call("disk_inventory"), self.show_payload))
        elif command == "net":
            print(format_result(await direct.call("network_status"), self.show_payload))
        elif command == "gpu":
            print(format_result(await direct.call("gpu_status"), self.show_payload))
        elif command == "clip":
            if rest:
                print(format_result(await direct.call("clipboard",
                                                      {"action": "write", "text": rest}),
                                    self.show_payload))
            else:
                print(format_result(await direct.call("clipboard", {"action": "read"}),
                                    True))
        elif command == "open":
            print(format_result(await direct.call("open_target", {"target": rest}),
                                self.show_payload))
        elif command == "notify":
            print(format_result(await direct.call("notify", {"message": rest}),
                                self.show_payload))
        elif command == "media":
            print(format_result(await direct.call("media_control",
                                                  {"action": rest or "play_pause"}),
                                self.show_payload))
        elif command in {"volume", "brightness"}:
            try:
                value = int(rest)
            except ValueError:
                print("  usage: /volume 40   /brightness 60")
                return
            print(format_result(await direct.call("hardware_control",
                                                  {"target": command, "value": value}),
                                self.show_payload))
        elif command == "undo":
            print(format_result(await direct.call("hardware_undo"), self.show_payload))
        elif command == "search":
            print(format_result(await direct.call("search_documents", {"query": rest}),
                                True))
        elif command == "read":
            print(format_result(await direct.call("workspace_fs",
                                                  {"action": "read_text",
                                                   "relative_path": rest}), True))
        elif command == "write":
            path, _, body = rest.partition(" ")
            print(format_result(await direct.call("workspace_fs",
                                                  {"action": "write_text",
                                                   "relative_path": path,
                                                   "content": body}), self.show_payload))
        elif command == "remember":
            key, _, stored = rest.partition("=")
            print(format_result(await direct.call("remember",
                                                  {"key": key.strip(),
                                                   "value": stored.strip()}),
                                self.show_payload))
        elif command == "recall":
            print(format_result(await direct.call("recall", {"query": rest or None}), True))
        elif command == "macro":
            await self._macro(rest)
        elif command == "dry":
            wanted = rest.lower() in {"on", "1", "true", "yes"}
            if rest.lower() in {"on", "1", "true", "yes", "off", "0", "false", "no"}:
                policy.set_dry_run(wanted)
                self.orchestrator.dry_run = wanted
            print(f"  dry-run: {'on' if policy.dry_run_enabled() else 'off'}")
        elif command == "log":
            count = int(rest) if rest.isdigit() else 8
            for record in audit.tail(count):
                stamp = record.get("ts", "")
                print(f"  {stamp}  {record.get('event'):<14} "
                      f"{json.dumps({k: v for k, v in record.items() if k not in {'ts', 'event', 'pid'}}, default=str)[:150]}")
        elif command == "jail":
            print(f"  {config.WORKSPACE_JAIL_ROOT}")
        elif command == "capabilities":
            print(capability_card(await _tool_count()))
        elif command == "inventory":
            kind = rest or "services"
            payload: dict[str, Any] = {"kind": kind}
            if kind == "errors":
                payload["hours"] = 24
            print(format_result(await direct.call("system_inventory", payload),
                                self.show_payload))
        elif command == "remind":
            raw_minutes, _, text = rest.partition(" ")
            if not raw_minutes.isdigit() or not text.strip():
                print("  usage: /remind 20 take a break")
                return
            print(format_result(await direct.call("reminders",
                                                  {"action": "add",
                                                   "minutes": int(raw_minutes),
                                                   "text": text.strip()}),
                                self.show_payload))
        elif command == "reminders":
            print(format_result(await direct.call("reminders", {"action": "list"}), True))
        elif command == "focus":
            action = rest if rest in {"on", "off", "status"} else "on"
            print(format_result(await direct.call("focus_mode", {"action": action}),
                                self.show_payload))
        elif command == "organize":
            print(format_result(await direct.call("organize",
                                                  {"relative_path": rest, "apply": False}),
                                True))
        elif command == "history":
            memory = self.orchestrator.memory
            if not len(memory):
                print("  (no turns yet)")
            for index, turn in enumerate(memory.turns, start=1):
                print(f"  {index}. user: {turn.user[:90]}")
                print(f"     me:   {turn.assistant[:90]}")
            summary = memory.summary()
            if summary:
                print(f"  earlier: {summary[:400]}")
        elif command == "clear":
            self.orchestrator.memory.clear()
            print("  conversation cleared")
        elif command == "panic":
            policy.set_panic(True, reason="manual /panic")
            self.orchestrator.cancel()
            print("  PANIC: every action is blocked. /resume to re-enable.")
        elif command == "resume":
            policy.set_panic(False)
            self.orchestrator.reset_cancel()
            print("  actions re-enabled")
        else:
            print(f"  unknown command /{command}; try /help")

    async def _macro(self, rest: str) -> None:
        sub, _, name = rest.partition(" ")
        if sub in {"", "list"}:
            print(format_result(await self.direct.call("list_profiles"), True))
            return
        if sub == "run":
            result = await self.orchestrator.run_profile(name.strip())
            print(format_agent_result(result, self.show_payload))
            return
        if sub == "save":
            print("  saving routines is done from Python: see start.md (macros section)")
            return
        print("  usage: /macro list   /macro run <name>")


class _MissingModel:
    """Stand-in used when the model is unavailable, so direct commands still work."""

    name = "unavailable"

    def complete(self, messages, schema=None):
        raise LLMUnavailable(
            "No local model is loaded, so free-form requests are unavailable.\n"
            "Use a slash command (see /help) or configure a model: see start.md."
        )


# --------------------------------------------------------------------------- selftest
async def selftest() -> int:
    """Fast, model-free verification of the delivered behaviour."""
    direct = DirectClient()
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))

    tools = await _tool_names()
    record("tool registry", len(tools) >= 28, f"{len(tools)} tools published")
    for expected in ("machine_health", "hardware_control", "app_lifecycle",
                     "power_session", "workspace_fs", "clipboard", "search_documents"):
        record(f"tool:{expected}", expected in tools, "registered" if expected in tools else "missing")

    health = await direct.call("machine_health")
    record("machine_health", health.get("status") == "success",
           health.get("summary", "")[:70])

    traversal = await direct.call("workspace_fs",
                                  {"action": "read_text", "relative_path": "../../etc/passwd"})
    record("jail blocks traversal", traversal.get("status") == "error",
           traversal.get("summary", "")[:70])

    write = await direct.call("workspace_fs", {"action": "write_text",
                                               "relative_path": "selftest.txt",
                                               "content": "selftest"})
    record("jail write", write.get("status") in {"success", "requires_confirmation"},
           write.get("summary", "")[:70])
    read = await direct.call("workspace_fs", {"action": "read_text",
                                              "relative_path": "selftest.txt"})
    record("jail read", read.get("status") == "success", read.get("summary", "")[:70])

    remember = await direct.call("remember", {"key": "selftest", "value": "ok"})
    recall = await direct.call("recall", {"key": "selftest"})
    record("memory store", remember.get("status") == "success"
           and recall.get("status") == "success"
           and bool(recall.get("payload", {}).get("entries")),
           recall.get("summary", "")[:70])

    inventory = await direct.call("system_inventory", {"kind": "services"})
    record("inventory degrades honestly",
           inventory.get("status") in {"success", "unsupported"},
           inventory.get("summary", "")[:70])

    reminder = await direct.call("reminders", {"action": "add", "minutes": 5,
                                               "text": "selftest reminder"})
    reminder_id = (reminder.get("payload", {}).get("reminder") or {}).get("id")
    cancelled = await direct.call("reminders", {"action": "cancel",
                                                "reminder_id": reminder_id})
    record("reminders round trip",
           reminder.get("status") == "success" and cancelled.get("status") == "success",
           "added and cancelled")

    plan = await direct.call("organize", {"relative_path": ""})
    record("organise plans without moving",
           plan.get("status") == "success"
           and plan.get("payload", {}).get("requires_apply") is True,
           plan.get("summary", "")[:70])

    from agent.classifier import classify
    intent = classify("how much disk space is left")
    record("classifier shortcut", intent is not None and intent.tool == "disk_inventory",
           f"{intent.tool} in <1 ms" if intent else "no match")

    policy.set_panic(True, reason="selftest")
    try:
        blocked = await direct.call("power_session", {"action": "shutdown"})
        record("panic switch blocks actions",
               blocked.get("status") == "cancelled",
               blocked.get("summary", "")[:70])
    finally:
        policy.set_panic(False)

    card = capability_card(len(tools))
    record("capability card", "WHAT I CAN TOUCH" in card,
           f"{len(card.splitlines())} lines")

    power = await direct.call("power_session", {"action": "shutdown"})
    record("shutdown needs confirmation", power.get("status") == "requires_confirmation",
           power.get("summary", "")[:70])
    token = str(power.get("confirmation_token") or "")

    from mcp_server import security
    record("token is single use",
           security.verify_and_consume_token(token, "shutdown") is not None
           and security.verify_and_consume_token(token, "shutdown") is None,
           "verified once, replay rejected")

    kill = await direct.call("app_lifecycle", {"action": "request_kill", "pid": 1})
    record("protected process refused", kill.get("status") == "error",
           kill.get("summary", "")[:70])

    launch = await direct.call("app_lifecycle", {"action": "launch", "app_name": "rm -rf /"})
    record("launch allowlist", launch.get("status") == "error",
           launch.get("summary", "")[:70])

    policy.set_dry_run(True)
    try:
        dry = await direct.call("power_session", {"action": "shutdown"})
        record("dry-run simulates", dry.get("status") == "dry_run",
               dry.get("summary", "")[:70])
    finally:
        policy.set_dry_run(False)

    print("\nSELFTEST")
    width = max(len(name) for name, _, _ in results)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        print(f"  {'[pass]' if ok else '[FAIL]'} {name:<{width}}  {detail}")
    print(f"\n  {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


async def watch(args: argparse.Namespace) -> int:
    """Foreground scheduler: due reminders + one health report per day."""
    from agent.scheduler import Scheduler

    direct = DirectClient()
    scheduler = Scheduler(report_at=args.report_at,
                          report_enabled=not args.no_report)
    interval = max(5, int(args.interval))
    print(f"watching every {interval}s"
          + (f", daily report at {args.report_at}" if scheduler.report_enabled else "")
          + "  (Ctrl+C to stop)")
    try:
        while True:
            listed = await direct.call("reminders", {"action": "list"})
            pending = listed.get("payload", {}).get("reminders", [])
            for action in scheduler.tick(pending):
                if action.kind == "reminder":
                    await direct.call("reminders",
                                      {"action": "due"})       # marks it fired
                    print(f"  {action.summary}", flush=True)
                    await direct.call("notify", {"title": "Reminder",
                                                 "message": action.summary})
                else:
                    health = await direct.call("machine_health")
                    print(f"  {action.summary}: {health.get('summary', '')}", flush=True)
                    await direct.call("notify", {"title": "Daily health report",
                                                 "message": health.get("summary", "")})
            if getattr(args, "once", False):
                return 0
            scheduler.sleep(interval)
    except KeyboardInterrupt:
        print("\nwatch stopped")
        return 0


async def _tool_count() -> int:
    return len(await _tool_names())


async def _tool_names() -> list[str]:
    from fastmcp import Client

    from mcp_server.server import mcp

    async with Client(mcp) as client:
        return [tool.name for tool in await client.list_tools()]


# --------------------------------------------------------------------------- entry
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description=BANNER)
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start the interactive agent (default)")
    run.add_argument("--once", metavar="TEXT", help="handle one request and exit")
    run.add_argument("--dry-run", action="store_true", help="simulate every action")
    run.add_argument("--json", action="store_true", help="print full payloads")
    run.add_argument("--max-steps", type=int, default=None)
    run.add_argument("--script", metavar="FILE", help="replay model replies (testing)")
    run.add_argument("--no-card", dest="quiet_card", action="store_true",
                     help="do not print the capability card on startup")
    run.add_argument("--no-classifier", dest="no_classifier", action="store_true",
                     help="always use the model, never the shortcut classifier")

    watch_cmd = sub.add_parser("watch", help="foreground scheduler: reminders + daily report")
    watch_cmd.add_argument("--interval", type=int, default=30,
                           help="seconds between checks (default 30)")
    watch_cmd.add_argument("--report-at", default="09:00",
                           help="time of day for the health report (HH:MM)")
    watch_cmd.add_argument("--no-report", action="store_true",
                           help="reminders only, no daily health report")
    watch_cmd.add_argument("--once", action="store_true",
                           help="check once and exit (for cron/Task Scheduler)")

    sub.add_parser("doctor", help="check the environment")
    sub.add_parser("tools", help="list registered tools")
    sub.add_parser("selftest", help="run model-free acceptance checks")
    return parser


async def _run(args: argparse.Namespace) -> int:
    llm: Any = None
    if getattr(args, "script", None):
        with open(args.script, encoding="utf-8") as fh:
            llm = ScriptedLLM([line for line in fh.read().split("\n---\n") if line.strip()])
    else:
        try:
            llm = load_default_llm()
            print(f"model loaded: {config.MODEL_PATH.name}")
        except LLMUnavailable as exc:
            print(f"! {exc}")

    interactive = sys.stdin.isatty()
    session = Session(llm=llm, dry_run=True if args.dry_run else None,
                      show_payload=args.json, interactive=interactive)
    if args.max_steps:
        session.orchestrator.max_steps = args.max_steps
    if getattr(args, "no_classifier", False):
        session.orchestrator.use_classifier = False

    print("=" * 62)
    print(f" {BANNER}  |  jail: {config.WORKSPACE_JAIL_ROOT}")
    print(f" mode: {'dry-run' if policy.dry_run_enabled() else 'live'}"
          f"  |  model: {getattr(llm, 'name', 'unavailable')}")
    print(" /help for commands, /quit to exit")
    print("=" * 62)
    if interactive and not args.quiet_card:
        print(capability_card(await _tool_count()))
        print("=" * 62)

    if args.once:
        keep_going = await session.handle(args.once)
        return 0 if keep_going else 0

    if interactive:
        while True:
            try:
                line = input("\nyou > ")
            except (EOFError, KeyboardInterrupt):
                print("\nexiting")
                return 0
            try:
                keep_going = await session.handle(line)
            except KeyboardInterrupt:
                # Panic stop: abort the request in flight and block further actions
                # until the operator explicitly resumes.
                policy.set_panic(True, reason="Ctrl+C during a request")
                session.orchestrator.cancel()
                print("\n  PANIC: request aborted, every action is blocked. "
                      "String /resume to re-enable.")
                continue
            if not keep_going:
                return 0

    # non-interactive: process a stream of lines
    for line in sys.stdin:
        if not await session.handle(line):
            break
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "doctor":
        return doctor_module.main()
    if args.command == "selftest":
        return asyncio.run(selftest())
    if args.command == "watch":
        return asyncio.run(watch(args))
    if args.command == "tools":
        for name in sorted(asyncio.run(_tool_names())):
            print(name)
        return 0

    if args.command is None:
        args = parser.parse_args(["run"])
    elif args.command != "run":
        parser.print_help()
        return 2
    return asyncio.run(_run(args))
