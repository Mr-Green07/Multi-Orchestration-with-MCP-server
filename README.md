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

## MCP tools

The server exposes five tools:

| Tool | Purpose | Supported values |
| --- | --- | --- |
| `system_telemetry` | Read system metrics | `cpu`, `memory`, `disk`, `battery` |
| `hardware_control` | Change Windows hardware settings | `target`: `volume`, `mute`, `brightness`; `value`: `0-100` |
| `app_lifecycle` | List, launch, or request termination of applications | `action`: `launch`, `list_running`, `request_kill` |
| `workspace_fs` | Inspect files in the workspace jail | `action`: `list`, `read_text`, `search` |
| `power` | Lock or change the power state | `action`: `lock_screen`, `sleep`, `restart`, `shutdown` |

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

Start the MCP server:

```powershell
python -m mcp_server.server
```

Run the orchestrator:

```powershell
python orchestrator/agent.py
```

Run the tests:

```powershell
pytest
```
