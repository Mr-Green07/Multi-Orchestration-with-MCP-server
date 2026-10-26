# Feature Roadmap — Multi-Orchestration-with-MCP-server

A feature list for making this agent **more advanced, more reliable on your actual PC, and simpler to use** — without turning it into a research project.

Legend

- **Effort** — `S` = under a day · `M` = 2–4 days · `L` = 1–2 weeks
- **Feasibility** — `High` = fits the current stack as-is · `Medium` = needs a new dependency or a new Windows API · `Low` = possible but fights the design or the hardware
- **Value** — `★★★` do first · `★★` good next · `★` nice-to-have

---

## 0. Where the agent stands today (the baseline the list is built on)

| Piece | Current state |
|---|---|
| Tools | 5 MCP tools: `system_telemetry`, `hardware_control`, `app_lifecycle`, `workspace_fs`, `power_session` |
| Brain | 4B GGUF local model, single-shot router: one user message → one JSON tool call → raw payload printed |
| Guidance | Grammar-constrained JSON, `oneOf` per tool built dynamically from MCP schemas |
| Safety | Confirmation token for `restart`/`shutdown` only; path-traversal check in the workspace jail |
| Windows layer | `pycaw` for volume, PowerShell/WMI for brightness, `shutdown` for power |
| Interface | `input()` REPL, prints the payload dict |

That's a solid foundation. Almost every "advanced" feature below is an extension of something already half-present.

---

## 1. Reliability & trust — "it must not surprise me on my own machine"

This is the highest-value group. A 4B model will occasionally pick the wrong tool or the wrong number; the system has to absorb that.

| # | Feature | What it does | Why it matters | Effort | Feasibility | Value |
|---|---|---|---|---|---|---|
| 1.1 | **Approval gate on *every* destructive action** | Extend the existing token pattern (`create_confirmation_token`) to `request_kill`, app launch, and any future file write/delete | Today only restart/shutdown ask. Kill and launch execute on trust | S | High | ★★★ |
| 1.2 | **Signed, single-use, expiring tokens everywhere** | Already built in `mcp_server/security.py` (120s TTL) — reuse it instead of one-off checks | Prevents replayed or model-invented confirmations | S | High | ★★★ |
| 1.3 | **Protected-process denylist** | Refuse to kill `explorer.exe`, `csrss.exe`, `winlogon.exe`, `lsass.exe`, `dwm.exe`, antivirus | One bad PID = dead session or worse | S | High | ★★★ |
| 1.4 | **Verify-after-act** | After setting volume/brightness, read the value back and report `applied: true/false` | Turns "I ran the command" into "the setting actually changed" | S | High | ★★★ |
| 1.5 | **Audit trail (JSONL)** | Append every request, decision, tool call, argument, result and approval to `logs/audit-YYYY-MM-DD.jsonl` | "What did it do to my PC at 3pm?" becomes answerable | S | High | ★★★ |
| 1.6 | **Dry-run mode** | `--dry-run` or "what would you do?" → shows the resolved tool + arguments, executes nothing | Cheap way to build trust before enabling real actions | S | High | ★★★ |
| 1.7 | **Undo where physically possible** | Remember previous volume/brightness/mute; snapshot running apps before kill; recycle bin instead of delete | Volume/brightness undo is trivial and feels magic | M | High | ★★ |
| 1.8 | **Rate limit + cooldown on power actions** | Max N power actions per hour, minimum gap between shutdown attempts | Stops a retry loop from rebooting your PC repeatedly | S | High | ★★ |
| 1.9 | **Panic stop** | Global hotkey / `Ctrl+C` handler / tray "STOP" that aborts the current tool and disables the agent | The one feature you want and hope never to use | M | Medium | ★★★ |
| 1.10 | **One jail root, defined once** | `workspace.py` hardcodes `new_workspace` while `config.py` defines `WORKSPACE_JAIL_ROOT` — they disagree | Two jails means the agent can see files you think it can't | S | High | ★★★ |
| 1.11 | **Startup capability card** | Print exactly what the agent can touch on your machine, in plain English, on boot | "Advanced" without "opaque" | S | High | ★★ |
| 1.12 | **Structured error taxonomy** | Every error gets `code` + `retryable` + `user_hint` instead of a bare string | Lets the model retry intelligently instead of hallucinating | S | High | ★★ |
| 1.13 | **Explicit scoped elevation check** | Detect when an action needs admin, say so, don't fail silently | Brightness and service actions fail cryptically today | S | High | ★★ |
| 1.14 | **No `shell=True` in process launch** | `Popen(cmd, shell=True)` on a model-influenced path | Removes an injection surface for near-zero cost | S | High | ★★★ |

---

## 2. Awareness — "it knows what's actually on my computer"

Cheap to add, and this is what makes an agent feel advanced.

| # | Feature | What it does | Effort | Feasibility | Value |
|---|---|---|---|---|---|
| 2.1 | **One-call health snapshot** | `machine_health` → CPU, RAM, disk, battery, network, GPU, uptime, and a one-line verdict ("fine / disk 93% full") | S | High | ★★★ |
| 2.2 | **Top-N resource hogs** | Merge `list_running` with CPU% and RAM% sorted, not just RAM > 0.5% | S | High | ★★★ |
| 2.3 | **GPU telemetry** | `nvidia-smi --query-gpu` if present, else WMI fallback; note when absent | S | High | ★★ |
| 2.4 | **Network telemetry** | Throughput, active Wi-Fi SSID + signal, default gateway reachability | S | High | ★★ |
| 2.5 | **Per-disk inventory** | All volumes, not just `Path.cwd().anchor` | S | High | ★★★ |
| 2.6 | **Startup & services status** | Windows services state, startup items, scheduled tasks — read-only | M | Medium | ★★ |
| 2.7 | **Installed apps list** | `winget list` / registry uninstall keys, cached | M | Medium | ★★ |
| 2.8 | **Recent errors** | Last 24h of Windows Event Log errors, summarized | M | Medium | ★★ |
| 2.9 | **Clipboard read/write** | Copy a summary to clipboard, or read what you just copied | S | High | ★★★ |
| 2.10 | **Screenshot into the jail** | `screenshot` tool writes a PNG into the workspace | S | High | ★★ |
| 2.11 | **Screen *understanding*** | Feed that PNG to a small vision model | L | Medium | ★ |
| 2.12 | **Window awareness** | List open windows, focus a window, minimize all | M | Medium | ★★ |
| 2.13 | **Battery-aware behavior** | On battery < 20%, refuse heavy actions and suggest power saving | S | High | ★ |
| 2.14 | **Read-only access outside the jail** | Opt-in scopes (Downloads, Documents) with explicit config, never write | M | High | ★★ |

---

## 3. Everyday usefulness — actions you'd actually ask for

| # | Feature | What it does | Effort | Feasibility | Value |
|---|---|---|---|---|---|
| 3.1 | **Open things** | Open a file, folder, URL, or app by name (`os.startfile`, allowlisted) | S | High | ★★★ |
| 3.2 | **Profile / macro mode** | "Work setup" = open VS Code + browser + terminal + mute notifications, one command | M | High | ★★★ |
| 3.3 | **Media control** | Play/pause/next via Windows media session API | M | Medium | ★★ |
| 3.4 | **Notifications back to you** | Toast when a long task finishes | S | High | ★★ |
| 3.5 | **Timers & reminders** | "Remind me in 20 minutes", persisted to SQLite | M | High | ★★ |
| 3.6 | **Focus / DND toggle** | Mute notifications + set volume in one action | M | Medium | ★★ |
| 3.7 | **File organization** | Suggest moves/renames in Downloads, **dry-run first**, recycle bin for removals | M | High | ★★ |
| 3.8 | **Ask my own files (RAG)** | The repo already has a FAISS + sentence-transformers retriever in `tools.py` — wire it to the MCP server and index `~/AgentWorkSpace` | M | High | ★★★ |
| 3.9 | **"Remember this"** | SQLite facts/preferences the agent can recall across sessions | M | High | ★★★ |
| 3.10 | **Scheduled runs** | "Every morning give me a health report" | M | Medium | ★ |

---

## 4. Brain upgrades — more advanced reasoning without a bigger model

| # | Feature | What it does | Why it matters | Effort | Feasibility | Value |
|---|---|---|---|---|---|---|
| 4.1 | **Multi-step loop, unified** | `agent_controller.py` already implements a proper tool→observe→answer loop; `orchestrator/agent.py` is single-shot. Merge them | Biggest capability jump available to you | M | High | ★★★ |
| 4.2 | **Natural-language final answer** | After the tool runs, one more model call turns the payload into a sentence; keep raw JSON behind `--verbose` | Today it prints a dict | S | High | ★★★ |
| 4.3 | **Self-repair on tool failure** | On error, one retry with corrected arguments (bounded to 1–2 attempts) | Kills most "it said it failed" outcomes | S | High | ★★★ |
| 4.4 | **Clarify instead of guess** | Add an `ask_user` action to the protocol when confidence is low or params are ambiguous | A 4B model *will* guess otherwise | S | High | ★★★ |
| 4.5 | **Per-tool few-shot examples** | 1–2 example calls per tool, generated from the real schema | Small models live and die by examples; costs almost nothing | S | High | ★★★ |
| 4.6 | **Conversation memory** | Last N turns + rolling summary, so "make it quieter" resolves "it" | Required for anything conversational | M | High | ★★ |
| 4.7 | **Larger context** | `n_ctx=1024` is tiny; 2048–4096 usually still fits a 4B Q4 | More tools and history stop falling off the prompt | S | High | ★★★ |
| 4.8 | **Config-driven model loading** | GGUF path, ctx, batch, GPU layers, CPU fallback in `config.py` | Model swap without editing code | S | High | ★★ |
| 4.9 | **Tool-result summarization cap** | Compress oversized outputs before they re-enter the prompt | Prevents context blowups on big searches | S | High | ★★ |
| 4.10 | **Tiny tool classifier** | Match obvious commands ("lock screen") to a tool in <50ms, skip inference | Latency win, and a fallback when the model is unsure | M | Medium | ★★ |
| 4.11 | **Confidence reporting** | "Not sure — did you mean volume or mute?" | Reliability you can *see* | S | High | ★★ |
| 4.12 | **Prompt-cache-friendly ordering** | Stable system prompt prefix, dynamic tool block last | Faster repeated calls on llama.cpp | S | High | ★ |

---

## 5. Simplicity — one thing to start, nothing to babysit

| # | Feature | What it does | Effort | Feasibility | Value |
|---|---|---|---|---|---|
| 5.1 | **One entry point** | `python -m agent` boots server + client together, with `run / doctor / tools` subcommands | Today it's two terminals and two files | S | High | ★★★ |
| 5.2 | **Slash commands** | `/tools`, `/health`, `/log`, `/approve`, `/undo`, `/dry`, `/quit` | Power without menus | S | High | ★★★ |
| 5.3 | **Non-blocking approval** | `input()` inside the async loop freezes everything; move approval to a callback/tray/toast | A blocked prompt during a tool call is a hang | M | Medium | ★★ |
| 5.4 | **Tray icon or minimal local UI** | Status dot, approve/deny buttons, last 5 actions | Friendlier than a terminal for a desktop agent | M | Medium | ★★ |
| 5.5 | **Global hotkey** | `Ctrl+Alt+Space` opens the prompt from anywhere | Turns it into a real desktop tool | M | Medium | ★★ |
| 5.6 | **Streaming + progress** | Show "thinking… → calling hardware_control… → done" | Removes the "is it frozen?" feeling | S | High | ★★ |
| 5.7 | **`doctor` command** | Checks model file, deps, pycaw, PowerShell, brightness support, jail path, permissions — one green/red list | Instantly explains 80% of setup failures | S | High | ★★★ |
| 5.8 | **Single-file installer / packaged exe** | PyInstaller or a setup script | No venv archaeology | M | Medium | ★ |
| 5.9 | **Voice (offline)** | whisper.cpp in, Piper out | Very "advanced", keeps the offline promise | L | Medium | ★ |

---

## 6. Engineering hygiene — the unglamorous reliability work

| # | Gap / Feature | Detail | Effort | Value |
|---|---|---|---|---|
| 6.1 | **Dependency drift** | `llama-cpp-python`, `pycaw`, `comtypes`, `pywin32` are imported but missing from `requirements.txt`; `pyproject.toml` lists a different set. One source of truth | S | ★★★ |
| 6.2 | **Blocking telemetry call** | `psutil.cpu_percent(interval=1)` blocks the async event loop for a full second; use `interval=0.1` or a thread | S | ★★★ |
| 6.3 | **Two security modules** | Root `security.py` and `mcp_server/security.py` are unrelated; one is easily mistaken for the other | S | ★★★ |
| 6.4 | **Two agent brains** | `agent_controller.py` and `orchestrator/agent.py` implement different loops; pick one | M | ★★★ |
| 6.5 | **CI runs one test file** | Only `tests/test_mcp_server.py` runs in CI; the agent, JSON and security suites don't. The `addopts` in `pyproject.toml` also silently skips `test_agent.py` and `test_metrics.py` | S | ★★★ |
| 6.6 | **`request_kill` never kills** | It always returns `requires_confirmation` and no second phase exists | S | ★★★ |
| 6.7 | **No timeout on app launch** | `Popen` without a readiness check reports success even when the exe is missing | S | ★★ |
| 6.8 | **Unbounded search** | `workspace_fs search` walks the whole tree with no match/file/size cap | S | ★★ |
| 6.9 | **Contract tests** | Assert server signature ↔ Literal values ↔ README table ↔ tool schema all agree | S | ★★★ |
| 6.10 | **Tool versioning** | `TOOL_SCHEMA_VERSION` so prompt caches invalidate correctly | S | ★ |
| 6.11 | **Correlation ID per request** | One ID threaded through logs for each user turn | S | ★★ |
| 6.12 | **Metrics** | Tool latency, success rate, tokens/sec, peak RAM | S | ★★ |
| 6.13 | **Graceful degradation** | Missing pycaw / no battery / no PowerShell → tool reports `unsupported`, not a stack trace | S | ★★ |

---

## 7. What I'd honestly call out of scope (or later)

Being explicit about the non-starters is as useful as the list itself.

| Idea | Verdict | Why |
|---|---|---|
| Cloud LLM / web browsing | **Skip** | Breaks the offline, local-only premise that makes the safety story work |
| macOS / Linux hardware control | **Later, separate backends** | `pycaw` and WMI brightness are Windows-only; a Linux port is a new module, not a patch |
| Arbitrary GUI automation (click/type anywhere) | **Skip for now** | A 4B model on unstructured screens is unreliable and unrecoverable; stick to named actions |
| Email / calendar integration | **Skip while offline** | Needs OAuth + network; contradicts the design |
| Registry edits, driver installs, service reconfiguration | **Skip** | High blast radius, low payoff, hard to undo |
| Continuous screen watching / always-on mic | **Skip** | Privacy and constant CPU/GPU cost on a 4B local model |
| File deletion | **Avoid — recycle bin only** | Irreversible actions are the one category an agent shouldn't own |
| Full autonomous multi-tool chains with no approval | **Skip** | Every extra autonomous step multiplies the blast radius on your real machine |

---

## 8. Suggested order (three passes)

**Pass 1 — make it trustworthy and honest (≈1 week)**
`1.1` `1.3` `1.4` `1.5` `1.10` `1.14` · `4.2` `4.5` `4.7` · `6.1` `6.2` `6.5`
→ Same five tools, but every action is verified, logged, and undoable-ish, and the answer comes back in English.

**Pass 2 — make it useful daily (≈1–2 weeks)**
`2.1` `2.2` `2.9` `2.5` · `3.1` `3.2` · `4.1` `4.3` `4.4` · `5.1` `5.2` `5.7`
→ One command, health snapshot, macros, clipboard, a real planning loop, and a `doctor` that explains itself.

**Pass 3 — make it feel advanced (≈2+ weeks)**
`1.7` `1.9` `1.6` · `3.8` `3.9` · `2.6` `2.7` `2.8` `3.4` · `5.5` `5.4` · `6.9` `6.12`
→ Undo, panic stop, ask-my-files, memory, Windows system awareness, hotkey, tray UI, test coverage.

---

### The one-line summary

Your agent is already a clean router with a real safety primitive. The highest-leverage additions are not new tools — they are **verify-after-act, an audit log, an approval gate on everything destructive, a multi-step loop with clarifying questions, and one entry point**. Everything else is surface area.
