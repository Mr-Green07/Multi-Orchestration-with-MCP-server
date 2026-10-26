"""Benchmark harness: measures the deterministic (non-LLM) layers of the agent.

Run with the repo root on sys.path:
    python report/benchmark.py
Writes report/bench_results.json
"""
from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psutil  # noqa: E402

from mcp_server.schemas import SystemToolResponse  # noqa: E402
from mcp_server.security import create_confirmation_token, verify_and_consume_token  # noqa: E402
from mcp_server.tools import lifecycle, power, workspace  # noqa: E402

import security as root_security  # noqa: E402
import tools as root_tools  # noqa: E402


def timeit(fn, n=200, warmup=10):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)  # ms
    samples.sort()
    return {
        "n": n,
        "mean_ms": round(statistics.fmean(samples), 4),
        "p50_ms": round(samples[len(samples) // 2], 4),
        "p95_ms": round(samples[int(len(samples) * 0.95)], 4),
        "max_ms": round(samples[-1], 4),
    }


def bench_telemetry():
    out = {}
    out["cpu"] = timeit(lambda: psutil.cpu_percent(interval=0.1), n=60, warmup=3)
    out["memory"] = timeit(lambda: psutil.virtual_memory()._asdict(), n=200)
    out["disk"] = timeit(lambda: psutil.disk_usage("/")._asdict(), n=200)
    out["battery"] = timeit(lambda: psutil.sensors_battery(), n=200)
    out["process_scan"] = timeit(
        lambda: [
            p.info for p in psutil.process_iter(["pid", "name", "memory_percent"])
            if p.info.get("memory_percent")
        ],
        n=60,
    )
    return out


def bench_workspace():
    jail = Path(workspace.JAIL_ROOT)
    jail.mkdir(parents=True, exist_ok=True)
    (jail / "bench_doc.txt").write_text("alpha beta gamma\n" * 200, encoding="utf-8")
    for i in range(20):
        (jail / f"f{i}.txt").write_text(f"note {i}\n", encoding="utf-8")
    out = {}
    out["list"] = timeit(lambda: workspace.execute_workspace_fs("list", ""), n=200)
    out["read_text"] = timeit(lambda: workspace.execute_workspace_fs("read_text", "bench_doc.txt"), n=200)
    out["search"] = timeit(lambda: workspace.execute_workspace_fs("search", "", "note 7"), n=60)
    out["traversal_reject"] = timeit(
        lambda: workspace.execute_workspace_fs("read_text", "../../etc/passwd"), n=200
    )
    return out


def bench_app_lifecycle():
    return {
        "list_running": timeit(lambda: lifecycle.execute_app_lifecycle("list_running"), n=60),
        "request_kill_denied": timeit(
            lambda: lifecycle.execute_app_lifecycle("request_kill", pid=4), n=200
        ),
    }


def bench_confirmation():
    def issue():
        return create_confirmation_token("shutdown", {"target_action": "shutdown"})

    out = {"issue": timeit(issue, n=200)}
    token = issue()
    out["verify_ok"] = timeit(lambda: verify_and_consume_token(issue(), "shutdown"), n=200)
    out["verify_replay"] = timeit(lambda: verify_and_consume_token(token, "shutdown"), n=200)
    out["verify_tampered"] = timeit(
        lambda: verify_and_consume_token(token[:-4] + "0000", "shutdown"), n=200
    )
    return out


def bench_schema():
    def build():
        return SystemToolResponse(
            status="success",
            metric_or_action="cpu_usage",
            summary="cpu telemetry retrieved",
            payload={"usage_percent": 23.5},
        ).model_dump()

    return {"model_dump": timeit(build, n=500)}


def bench_dispatch():
    ctx = root_tools.ToolContext()
    return {
        "dispatch_calculate": timeit(
            lambda: root_tools.run_tool("calculate", {"expression": "12*sqrt(2)+7"}, ctx), n=500
        ),
        "validate_reject_bad_arg": timeit(
            lambda: root_tools.run_tool("calculate", {"expression": 42}, ctx), n=500
        ),
        "validate_reject_unknown_tool": timeit(
            lambda: root_tools.run_tool("rm_rf", {}, ctx), n=500
        ),
    }


def bench_controller_parse():
    sys.path.insert(0, str(ROOT))
    from agent_controller import extract_json, validate_action

    good = '{"action":"tool","tool":"system_telemetry","arguments":{"metric":"cpu"}}'
    noisy = "Sure! Here you go:\n```json\n" + good + "\n```\nHope that helps."
    bad = '{"action":"tool","tool":'

    def full(text):
        obj, _err = extract_json(text)
        return validate_action(obj) if obj is not None else None

    return {
        "parse_clean": timeit(lambda: full(good), n=1000),
        "parse_noisy_fenced": timeit(lambda: full(noisy), n=1000),
        "parse_malformed_graceful": timeit(lambda: full(bad), n=1000),
        "safe_eval": timeit(lambda: root_security.safe_eval("(25*4)/sqrt(16)"), n=1000),
        "path_traversal_guard": timeit(
            lambda: _guard(), n=1000
        ),
    }


def _guard():
    try:
        root_security.resolve_in_workspace("../../../etc/shadow")
        return False
    except root_security.SecurityError:
        return True


def main():
    results = {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
        },
        "telemetry": bench_telemetry(),
        "workspace": bench_workspace(),
        "app_lifecycle": bench_app_lifecycle(),
        "confirmation": bench_confirmation(),
        "schema": bench_schema(),
        "dispatch": bench_dispatch(),
        "controller": bench_controller_parse(),
    }
    out = Path(__file__).resolve().parent / "bench_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
