# Multi-Orchestration-with-MCP-server

[![M8ven Score](https://m8ven.ai/badge/mcp/mr-green07-multi-orchestration-with-mcp-server-yp5ylg?v=e0190fff2cff5ff3e5f2436fd0edcc37)](https://m8ven.ai/mcp/mr-green07-multi-orchestration-with-mcp-server-yp5ylg?s=readme)

An offline system-operations agent that uses a local LLM orchestrator to
discover and call tools exposed by a FastMCP server.

## Architecture

```text
User request
    -> SystemAgentOrchestrator
    -> FastMCP client
    -> SystemOperatorServer
    -> selected MCP tool
```

The orchestrator discovers the registered MCP tools at runtime, builds a
tool-specific prompt and strict JSON schema, and calls the selected tool with
validated arguments.

## Scientific RAG (`scientific_llm`)

A second, independent package: offline scientific-paper retrieval, hybrid search,
specialist agents with citation validation, and a three-system benchmark with
paired statistics. No model download, no API key, no third-party runtime dependency.

```bash
python -m scientific_llm demo      # index 10 papers, answer one question
python -m scientific_llm ask "How does citation validation reduce unsupported claims?"
python -m scientific_llm evaluate --compare
python -m scientific_llm serve --port 8017
```

20-question benchmark, k=5: relevance 0.617 (conventional RAG) → 0.729 (single
agent) → **0.783** (multi-agent), at 5.4 → 7.4 → 16.6 ms; relevance gain is
significant under a paired bootstrap (+0.167, 95% CI [+0.067, +0.283], p<0.001),
faithfulness is 1.000 for all three because the synthesiser is extractive. Design, per-requirement map and threats to validity:
[`SCIENTIFIC_LLM.md`](SCIENTIFIC_LLM.md) and
[`reports/benchmark_report.md`](reports/benchmark_report.md).

**New here? Read [`start.md`](start.md).** It is the single source of truth for how
to install, run and test the project, and it lists every roadmap feature with an
honest status (working / best-effort / unverifiable on a given host).

## MCP tools

The server publishes 28 tools (run `python -m agent tools` for the live list):

| Group | Tools |
| --- | --- |
| Telemetry (read-only) | `system_telemetry`, `machine_health`, `top_processes`, `disk_inventory`, `network_status`, `gpu_status` |
| Hardware | `hardware_control`, `hardware_undo` |
| Applications | `app_lifecycle` |
| Files | `workspace_fs` (jail only, plus opt-in read-only scopes) |
| Power | `power_session` |
| Desktop | `clipboard`, `screenshot`, `open_target`, `notify`, `media_control` |
| Knowledge | `remember`, `recall`, `forget`, `save_profile`, `list_profiles`, `get_profile`, `search_documents`, `index_status` |
| Awareness / routines | `system_inventory`, `reminders`, `focus_mode`, `organize` |

All tool responses use a structured result containing a status, action or
metric name, summary, and payload. Destructive operations such as application
termination requests, restart, and shutdown return `requires_confirmation`
instead of executing immediately. Workspace file operations are restricted to
the configured workspace jail and reject path traversal.

## Setup

Requires Python 3.12 or newer.

```powershell
pip install -e .
```

Set `WORKSPACE_JAIL_ROOT` to override the default workspace location
(`~/AgentWorkSpace`). The orchestrator also expects the local GGUF model at:

```text
models/Qwen3.5-4BQ/model.gguf
```

## Run

One entry point boots the client with the server in-process:

```powershell
python -m agent            # interactive REPL
python -m agent run --once "is my machine okay"
python -m agent doctor     # environment check
python -m agent tools      # published tools
python -m agent selftest   # model-free acceptance checks
python -m agent watch      # reminders + daily health report
```

Run the tests:

```powershell
pytest
```

Full instructions, the feature-status table and troubleshooting live in
[`start.md`](start.md).
