# start.md — how to start, test, and trust this project

One-page answer first, details below:

```powershell
git clone <this repo> ; cd Multi-Orchestration-with-MCP-server
python -m venv .venv ; .venv\Scripts\activate          # Windows
pip install -e ".[dev]"
python -m agent doctor        # what works on THIS machine
python -m agent selftest      # 24 acceptance checks, no model needed
python -m agent               # the interactive agent
```

A GGUF model is **optional**. Everything read-only, every slash command, the
doctor, the selftest and the whole test suite work without one.

---

## 1. What this is

An offline system-operations agent:

```text
your request
   -> shortcut classifier (obvious read-only questions, no model)
   -> local GGUF model (plans one JSON step at a time)
   -> FastMCP client -> SystemOperatorServer (28 tools)
   -> guarded action -> verified result -> audit log
```

Two layers, one process. The tools are a normal MCP server you can also point
another client at; the agent is a planner with a bounded loop, an approval gate and
an audit trail.

---

## 2. Requirements

| Item | Detail |
| --- | --- |
| Python | 3.10+ (3.12 recommended; CI uses 3.12) |
| OS | Windows 10/11 is the target. Linux works for everything except Windows-only backends (see §7) |
| Model | Any GGUF chat model, 4B Q4 recommended. Optional but needed for free-form requests |
| Disk | ~3 GB for the model, ~150 MB for the code and dependencies |

Core dependencies: `fastmcp`, `psutil`, `pydantic`. Optional: `llama-cpp-python`
(model), plus platform binaries listed in §5.

---

## 3. Install

### Windows (primary path)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If you want free-form requests, install the model runtime and drop a GGUF file in
place:

```powershell
pip install llama-cpp-python
mkdir models\qwen3-4b
# copy a Q4_K_M GGUF here, then point the agent at it:
$env:AGENT_MODEL_PATH = "models\qwen3-4b\model.gguf"
```

### Linux / macOS (no hardware backends)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
# optional desktop helpers: apt install xclip scrot libnotify-bin playerctl
#                             brightnessctl (laptops), wmctrl (window list)
```

`pip install -e .` reads `pyproject.toml`, which is the single source of truth for
dependencies; `requirements.txt` mirrors it for plain-`pip` users. **Do not edit
both** — change `pyproject.toml` and regenerate the list.

---

## 4. Start the project

### 4.1 Check the environment first

```powershell
python -m agent doctor
```

Prints one green/red line per capability: Python, each dependency, the model file,
the workspace jail, the audit directory, the MCP server (and how many tools it
published), the confirmation-token round trip, and every hardware/desktop backend.
Exit code is non-zero if a **required** check fails.

### 4.2 Prove the behaviour without a model

```powershell
python -m agent selftest
```

24 checks, all model-free: tool registry, jail traversal blocked, jail write/read,
memory store, inventory degradation, reminders round trip, organise plan,
classifier shortcut, panic switch, shutdown needs confirmation, token single-use,
protected process refused, launch allowlist, dry-run simulation, capability card.
Expect `24/24 checks passed`.

### 4.3 Use the agent

```powershell
python -m agent                          # interactive REPL + capability card
python -m agent run --once "is my machine okay"
python -m agent run --once "how much disk space is left"      # classifier, no model
python -m agent run --dry-run            # everything simulated
python -m agent run --json               # full payloads
```

Startup prints the **capability card** — what this host can and cannot touch, in
plain English — so you never have to discover a missing backend by failing.

### 4.4 Slash commands (work without the model)

| Command | Does |
| --- | --- |
| `/help` | full list |
| `/tools` | tools published by the server, with read-only/destructive flags |
| `/capabilities` | the capability card again |
| `/health` `/top [cpu]` `/disk` `/net` `/gpu` | telemetry, directly |
| `/inventory services\|startup\|apps\|errors\|windows` | read-only system inventory |
| `/volume 40` `/brightness 60` `/undo` | hardware, verified after the fact |
| `/clip [text]` `/open <path\|url>` `/notify <text>` `/media <action>` | desktop |
| `/search <query>` `/read <path>` `/write <path> <text>` | workspace jail |
| `/remember k = v` `/recall [query]` | persistent memory |
| `/remind 20 take a break` `/reminders` | reminders |
| `/focus on\|off` | quiet mode (volume down, DND where supported) |
| `/organize [path]` | **plan** a tidy-up; nothing moves |
| `/macro list` `/macro run <name>` | saved routines |
| `/dry on\|off` | toggle dry-run |
| `/log [n]` `/jail` `/history` `/clear` | inspection |
| `/panic` / `/resume` | panic stop / re-enable |
| `/quit` | exit |

Anything that is not a slash command goes to the planner.

### 4.5 Scheduled runs

```powershell
python -m agent watch                      # reminders + 09:00 health report
python -m agent watch --interval 60 --report-at 08:30
python -m agent watch --once --no-report   # single check, for Task Scheduler/cron
```

A foreground loop, no daemon: `Ctrl+C` stops it instantly.

### 4.6 Scripted replay (how the tests drive the planner)

```powershell
python -m agent run --once "check my machine" --script script.txt
```

`script.txt` holds model replies separated by lines containing `---`:

```json
{"action": "tool", "tool": "machine_health", "arguments": {}}
---
{"action": "final", "answer": "Memory is at 72 percent; nothing critical."}
```

---

## 5. Test the project

```powershell
pytest                      # 274 tests, ~3 s, no model, no hardware
ruff check mcp_server agent  # style + unused imports
mypy mcp_server agent --ignore-missing-imports   # type check, clean
python -m agent selftest    # 24 behavioural acceptance checks
python -m agent doctor      # environment truth
```

What the suite covers (all hermetic — temp dirs, mocked hardware, scripted model):

| File | Covers |
| --- | --- |
| `tests/test_mcp_server.py` | the MCP contract end-to-end through a FastMCP client |
| `tests/test_policy.py` | protected processes, launch allowlist, rate limits, elevation, panic |
| `tests/test_audit.py` | JSONL records, truncation, correlation IDs, never raising |
| `tests/test_workspace_jail.py` | traversal, caps, dry-run writes, read-only scopes |
| `tests/test_hardware.py` | verify-after-act, undo, unsupported backends |
| `tests/test_lifecycle_power.py` | two-phase kill, allowlist, launch approval, power rate limit |
| `tests/test_telemetry.py` | health verdict, top-N, disks, network, GPU absence |
| `tests/test_knowledge.py` | memory, forget, profiles, document search |
| `tests/test_new_features.py` | inventory, reminders, focus, organise, classifier, memory, panic, battery |
| `tests/test_scheduler.py` | due reminders, once-per-day report, bad times |
| `tests/test_orchestrator_loop.py` | bounded loop, repairs, ask_user, approvals, profile replay |
| `tests/test_orchestrator.py` | prompts, grammar schema, annotations, contract vs README |
| `tests/test_cli_doctor.py` | doctor checks, slash commands, formatting |
| `tests/test_agent.py`, `test_tools.py`, `test_metrics.py` | the legacy controller and tool suite |

CI (`.github/workflows/ci.yml`) runs lint → type check → full pytest → doctor →
selftest on Python 3.12.

---

## 6. Feature status (the honest table)

Legend — **Working / verified here** = exercised by the automated tests and by hand
on this Linux sandbox. **Best-effort** = implemented, degrades to a structured
`unsupported` response instead of crashing. **Windows-only** = implemented against
the Windows API, cannot be exercised on this Linux box: verify with `python -m
agent doctor` on your PC. **Not implemented** = deliberately out of scope.

### Tier 1 — reliability and trust

| # | Feature | Status | Notes |
| --- | --- | --- | --- |
| 1.1 | Approval gate on every destructive action | Working / verified | kill, overwrite, power, organise; optional launch gate (`AGENT_APPROVE_LAUNCH=1`) |
| 1.2 | Signed, single-use, expiring tokens | Working / verified | 120 s TTL, action-bound, replay rejected (tested) |
| 1.3 | Protected-process denylist | Working / verified | 43 names + our own PID refused |
| 1.4 | Verify-after-act | Working / verified | hardware re-reads the value; `applied` is the truth |
| 1.5 | Audit trail (JSONL) | Working / verified | `logs/audit-YYYY-MM-DD.jsonl`, truncated values, correlation IDs |
| 1.6 | Dry-run mode | Working / verified | `--dry-run`, `AGENT_DRY_RUN`, `/dry` |
| 1.7 | Undo where physically possible | Working (hardware) / Best-effort | volume & brightness restore; organise *moves*, never deletes |
| 1.8 | Rate limit + cooldown on power actions | Working / verified | 6/hour, 30 s minimum gap, per-action buckets |
| 1.9 | Panic stop | Working / verified | `Ctrl+C` mid-request and `/panic`; enforced in the server too |
| 1.10 | One jail root, defined once | Working / verified | `config.WORKSPACE_JAIL_ROOT`; `security.py` shares it |
| 1.11 | Startup capability card | Working / verified | printed on boot, `/capabilities` |
| 1.12 | Structured error taxonomy | Working / verified | `code` + `retryable` + `user_hint` on refusals |
| 1.13 | Scoped elevation check | Working / verified (detection) | returns `needs_elevation` + how to fix; **cannot** self-elevate |
| 1.14 | No `shell=True` in process launch | Working / verified | argv lists only, allowlisted |

### Tier 2 — awareness

| # | Feature | Status | Notes |
| --- | --- | --- | --- |
| 2.1 | One-call health snapshot | Working / verified | `machine_health` with a one-line verdict |
| 2.2 | Top-N resource hogs | Working / verified | CPU or memory, protected processes marked |
| 2.3 | GPU telemetry | Best-effort | `nvidia-smi` if present, else `unsupported` (no GPU here) |
| 2.4 | Network telemetry | Working / verified | interfaces + throughput; no packets sent |
| 2.5 | Per-disk inventory | Working / verified | all mounted volumes, fullest first |
| 2.6 | Startup & services status | Windows-only / best-effort on Linux | PowerShell + registry on Windows; `systemctl` elsewhere |
| 2.7 | Installed apps list | Windows-only / best-effort on Linux | registry Uninstall keys; `dpkg-query`/`rpm` fallback, cached |
| 2.8 | Recent errors | Windows-only | Event Log on Windows; `journalctl` on Linux (needs journal access — refused as `unsupported` in this container) |
| 2.9 | Clipboard read/write | Best-effort | PowerShell on Windows; needs `xclip`/`wl-copy` here |
| 2.10 | Screenshot into the jail | Best-effort | `PIL.ImageGrab` (Windows), `grim`/`scrot` on Linux |
| 2.11 | Screen *understanding* (vision) | Not implemented | roadmap's ★ item; no vision model wired in |
| 2.12 | Window awareness | Windows-only / best-effort on Linux | list only (no focus/minimise); `wmctrl`/`xdotool` elsewhere |
| 2.13 | Battery-aware behaviour | Working / verified (logic) | heavy actions refused below 20% unplugged; no battery here → inert |
| 2.14 | Read-only access outside the jail | Working / verified | `AGENT_READ_ONLY_ROOTS`, addressed as `@Downloads/...`; writes always refused |

### Tier 3 — everyday usefulness

| # | Feature | Status | Notes |
| --- | --- | --- | --- |
| 3.1 | Open things | Best-effort | `os.startfile` on Windows, `xdg-open`/`open` elsewhere; schemes allowlisted |
| 3.2 | Profile / macro mode | Working / verified | `save_profile` / `get_profile`; replay goes through the same gates |
| 3.3 | Media control | Windows-only / best-effort | media keys via `keybd_event`; `playerctl` on Linux |
| 3.4 | Notifications | Best-effort | toast on Windows, `notify-send` on Linux |
| 3.5 | Timers & reminders | Working / verified | SQLite-backed, survive restarts, `agent watch` fires them |
| 3.6 | Focus / DND toggle | Best-effort | volume guaranteed, DND only where the desktop accepts it |
| 3.7 | File organisation | Working / verified | plan first, token required to apply, moves only (no delete) |
| 3.8 | Ask my own files (RAG) | Working / verified | built-in TF-IDF ranker over the jail; no FAISS/torch needed |
| 3.9 | "Remember this" | Working / verified | SQLite facts, `remember`/`recall`/`forget` |
| 3.10 | Scheduled runs | Working / verified | `python -m agent watch` |

### Tier 4 — brain

| # | Feature | Status | Notes |
| --- | --- | --- | --- |
| 4.1 | Multi-step loop, unified | Working / verified | one loop (`agent/orchestrator.py`); `orchestrator/agent.py` is a compat shim |
| 4.2 | Natural-language final answer | Working / verified | payload → sentence; raw JSON behind `--json` |
| 4.3 | Self-repair on tool failure | Working / verified | `AGENT_MAX_REPAIRS` bounded retries with the error attached |
| 4.4 | Clarify instead of guess | Working / verified | `ask_user` action |
| 4.5 | Per-tool few-shot examples | Working / verified | generated from the live schema |
| 4.6 | Conversation memory | Working / verified | last 4 turns + rolling summary; `/history`, `/clear` |
| 4.7 | Larger context | Working / verified | `AGENT_N_CTX` default 2048 |
| 4.8 | Config-driven model loading | Working / verified | `AGENT_MODEL_PATH`, `AGENT_N_CTX`, `AGENT_N_BATCH`, `AGENT_GPU_LAYERS` |
| 4.9 | Tool-result summarisation cap | Working / verified | oversized observations compressed before re-entering the prompt |
| 4.10 | Tiny tool classifier | Working / verified | deterministic, sub-millisecond, `AGENT_CLASSIFIER=0` disables |
| 4.11 | Confidence reporting | Working / verified | model may return `confidence`; below 0.5 the answer is hedged |
| 4.12 | Prompt-cache-friendly ordering | Working / verified | stable system prefix, dynamic tool block last |

### Tier 5 — simplicity

| # | Feature | Status | Notes |
| --- | --- | --- | --- |
| 5.1 | One entry point | Working / verified | `python -m agent [run\|watch\|doctor\|tools\|selftest]` |
| 5.2 | Slash commands | Working / verified | see §4.4 |
| 5.3 | Non-blocking approval | Working | approval is a callback (`approve=`), not `input()` inside the loop; the default CLI callback is still a prompt |
| 5.4 | Tray icon / local UI | Not implemented | needs a GUI toolkit; the CLI is the UI for now |
| 5.5 | Global hotkey | Not implemented | needs a system-wide keyboard hook (`pynput`/Win32) |
| 5.6 | Streaming + progress | Working / verified | `thinking → calling tool → result` lines, flushed as they happen |
| 5.7 | `doctor` command | Working / verified | 16 checks, explains missing backends |
| 5.8 | Packaged exe | Not implemented | install from source; PyInstaller is a separate exercise |
| 5.9 | Voice (offline) | Not implemented | whisper.cpp/Piper not wired in |

### Tier 6 — engineering hygiene

| # | Item | Status |
| --- | --- | --- |
| 6.1 | Dependency drift | Fixed — `pyproject.toml` is authoritative, `requirements.txt` mirrors it |
| 6.2 | Blocking telemetry call | Fixed — short `cpu_percent` intervals, no 1 s stalls |
| 6.3 | Two security modules | Fixed — `mcp_server/security.py` is the token implementation; root `security.py` is the legacy logger/path layer |
| 6.4 | Two agent brains | Fixed — one loop, legacy module is a shim |
| 6.5 | CI runs one test file | Fixed — CI runs the full suite, lint and types |
| 6.6 | `request_kill` never kills | Fixed — honest two-phase kill with verification |
| 6.7 | No timeout on app launch | Fixed — launch has a readiness/timeout path |
| 6.8 | Unbounded search | Fixed — match/file/size/depth caps |
| 6.9 | Contract tests | Working — server signature ↔ literals ↔ README ↔ schema |
| 6.10 | Tool versioning | Working — `config.TOOL_SCHEMA_VERSION` |
| 6.11 | Correlation ID per request | Working — threaded through audit, tool responses |
| 6.12 | Metrics | Working — `tests/test_metrics.py` reports selection/argument/success rates |
| 6.13 | Graceful degradation | Working — missing backends return `unsupported`, never a traceback |

### Explicitly out of scope (roadmap §7)

Cloud LLMs / web browsing, arbitrary GUI automation, email-calendar, registry edits,
driver installs, continuous screen/mic capture, irreversible file deletion, and
fully autonomous chains with no approval. These are **not** implemented on purpose.

---

## 7. What could not be verified on this machine

This checkout was developed and tested in a headless Linux container. The following
are implemented but **must be confirmed on your Windows PC**:

1. `hardware_control` volume/mute (pycaw) and brightness (WMI) — no audio endpoint
   or backlight here.
2. `system_inventory` services/startup/apps/errors (PowerShell, registry, Event Log)
   — validated for shape and graceful failure only.
3. `clipboard`, `screenshot`, `notify`, `media_control`, `open_target`,
   `focus_mode` DND — no desktop session or notification daemon here.
4. `gpu_status` — no GPU; the `unsupported` path is what was tested.
5. `power_session` execution — the container refuses shutdown; only the
   confirmation/rate-limit/dry-run paths were exercised.
6. Real-model behaviour (4B GGUF) — `llama-cpp-python` is not installed here, so the
   planner was driven by `ScriptedLLM`. Prompting, parsing, repairs and the loop are
   covered by tests; *answer quality* is not.
7. Battery guard, window list, journald/Event Log access — no battery, no X server,
   no journal permissions here.

Run `python -m agent doctor` on your machine: it turns every one of these into a
pass/fail line.

---

## 8. Safety model in one screen

* **One jail.** `WORKSPACE_JAIL_ROOT` (default `./workspace`). Absolute paths,
  drive-relative paths, UNC paths, `..` traversal and symlink escapes are rejected.
  Reads outside it are possible only through explicitly configured read-only scopes.
* **Two-phase destructive actions.** Kill, overwrite, power and organise return
  `requires_confirmation` with a single-use, action-bound, 120-second token. The
  model never sees the token until you say yes.
* **Denylists before actions.** 43 protected process names, a four-entry launch
  allowlist, a URL scheme allowlist.
* **Verify after act.** A tool reports `applied: true` only after reading the value
  back.
* **Rate limits.** Power actions: 6/hour with a 30-second gap. Terminations: 10/hour.
* **Everything is logged.** `logs/audit-YYYY-MM-DD.jsonl`, one line per request,
  decision, tool call, approval and answer, each with a correlation ID.
* **Panic stop.** `Ctrl+C` mid-request or `/panic` blocks every changing action at
  the server edge until `/resume`.

---

## 9. Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `WORKSPACE_JAIL_ROOT` | `./workspace` | the only writable directory |
| `AGENT_READ_ONLY_ROOTS` | *(empty)* | `:`-separated dirs readable as `@Name/...` |
| `AGENT_MODEL_PATH` | `models/…/model.gguf` | GGUF file |
| `AGENT_N_CTX` / `AGENT_N_BATCH` / `AGENT_GPU_LAYERS` | 2048 / 256 / -1 | model loading |
| `AGENT_MAX_TOKENS` / `AGENT_TEMPERATURE` | 384 / 0.0 | generation |
| `AGENT_MAX_STEPS` / `AGENT_MAX_REPAIRS` | 4 / 1 | loop bounds |
| `AGENT_TOOL_TIMEOUT` | 10 | seconds per tool call |
| `AGENT_DRY_RUN` | off | simulate every action |
| `AGENT_AUDIT_DIR` / `AGENT_AUDIT_DISABLED` | `./logs` / off | audit location / kill switch |
| `AGENT_LOG_LEVEL` | `INFO` | logging |
| `AGENT_CONFIRM_TTL` | 120 | token lifetime (seconds) |
| `AGENT_MAX_POWER_PER_HOUR` / `AGENT_MIN_POWER_GAP` | 6 / 30 | power rate limit |
| `AGENT_MAX_KILLS_PER_HOUR` | 10 | termination rate limit |
| `AGENT_APPROVE_LAUNCH` | off | require a token before launching an app |
| `AGENT_CLASSIFIER` | on | deterministic shortcut classifier |
| `AGENT_MEMORY_TURNS` / `AGENT_MEMORY_CHARS` | 4 / 2400 | conversation memory budget |
| `AGENT_BATTERY_GUARD` / `AGENT_BATTERY_GUARD_ON` | 20 / on | battery-aware refusals |
| `AGENT_MAX_INVENTORY_ROWS` | 60 | inventory/directory caps |
| `AGENT_MEMORY_DB` | `./database/agent_memory.db` | memory + reminders + profiles |

---

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `No GGUF model found` | Only free-form requests are affected. Set `AGENT_MODEL_PATH`, or use slash commands / the classifier |
| `llama-cpp-python` build fails | `pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` (or the CUDA wheel index) |
| `unsupported: no volume backend` | Windows: `pip install pycaw comtypes`. Linux: install `pactl` |
| Brightness always `needs_elevation` | Run the terminal as administrator (Windows) / add your user to the `video` group (Linux) |
| Screenshot fails on Linux | `apt install grim` (Wayland) or `scrot` (X11) |
| Clipboard empty | `apt install xclip` or `wl-clipboard` |
| Everything says `unsupported` | You are probably in a container: no audio, no display, no battery. Run `python -m agent doctor` |
| A tool "did nothing" | Check `applied` in the response and the matching line in `logs/audit-*.jsonl` |
| Agent stuck / acting weird | `/panic` then `/resume`; or `/dry on` to inspect intent before real actions |
| Tests fail on import | Run pytest from the repo root (it puts the root on `sys.path`) |

---

## 11. Where things live

```text
agent/                  the planner: cli, orchestrator, llm, prompts, doctor,
                        classifier, history, capabilities, scheduler
mcp_server/             the tool server: server.py (28 tools), policy, audit,
                        schemas, security (tokens), tools/*
orchestrator/agent.py   compatibility shim over the one real loop
agent_controller.py     legacy controller, kept for its JSON extraction helpers
config.py               every knob, cap and path in one place
security.py             legacy logger/path layer, now sharing the single jail
tests/                  274 hermetic tests
start.md                this file
FEATURE_ROADMAP.md      the specification these features came from
```

---

## 12. Sixty-second acceptance walkthrough

```powershell
python -m agent doctor            # expect the model line red if you skipped §3
python -m agent selftest          # expect 24/24
pytest                            # expect 274 passed
python -m agent run --once "how much disk space is left"    # no model needed
python -m agent tools             # expect 28 tools
python -m agent                   # then: /health, /capabilities, /remind 1 stretch,
                                  #       /reminders, /panic, /resume, /log
```

If those seven lines behave as described, the project is installed and working.
