import re
import time
from dataclasses import dataclass
from typing import Any, Literal

RouteType = Literal["DIRECT_MCP_BYPASS", "DIRECT_RAG_AGENT", "FAST_SINGLE_TOOL", "MULTI_STEP_PLANNER"]

@dataclass
class IntentDecision:
    route: RouteType
    target_agent: Literal["mcp_direct", "agent1_router", "agent2_rag"]
    matched_tools: list[str]
    extracted_args: dict[str, Any] | None
    confidence: float
    latency_ms: float
    reason: str


class FastIntentClassifier:
    """
    Sub-millisecond Intent Classifier & Deterministic Slot Extractor.
    Executes routine MCP system commands with ZERO LLM calls when arguments are clear.
    """

    TOOL_PATTERNS: dict[str, list[str]] = {
        "system_telemetry": [
            r"\bcpu\b", r"\bmemory\b", r"\bram\b", r"\bdisk\b",
            r"\bbattery\b", r"\btelemetry\b", r"\busage\b", r"\bstats\b"
        ],
        "hardware_control": [
            r"\bvolume\b", r"\bmute\b", r"\bunmute\b", r"\bbrightness\b",
            r"\bscreen\b", r"\baudio\b", r"\bspeaker\b", r"\bbacklight\b"
        ],
        "app_lifecycle": [
            r"\blaunch\b", r"\bopen\b", r"\bprocess\b", r"\bprocesses\b",
            r"\brunning\b", r"\bkill\b", r"\bvscode\b", r"\bbrowser\b",
            r"\bcalculator\b", r"\bterminal\b", r"\bpid\b"
        ],
        "workspace_fs": [
            r"\bfile\b", r"\bfiles\b", r"\bfolder\b", r"\bworkspace\b",
            r"\bread\b", r"\bwrite\b", r"\bsave\b", r"\bsearch\b", r"\blist\b"
        ],
        "power_session": [
            r"\block\b", r"\bsleep\b", r"\brestart\b", r"\breboot\b",
            r"\bshutdown\b", r"\bshut down\b", r"\bpower off\b"
        ],
    }

    RAG_PATTERNS: list[str] = [
        r"\brag\b", r"\bhealth report\b", r"\bpolicy\b", r"\bguidelines\b",
        r"\bdiagnostic report\b", r"\banalyze.*health\b", r"\bdocument\b",
        r"\bthreshold\b", r"\bhealth_report\b"
    ]

    MULTI_STEP_CONJUNCTIONS: list[str] = [
        r"\band then\b", r"\bthen\b", r"\bafter that\b", r"\band save\b",
        r"\band write\b", r"\band set\b", r"\band check\b"
    ]

    def _try_extract_args(self, tool: str, text: str) -> dict[str, Any] | None:
        """Attempt deterministic parameter extraction to bypass the LLM entirely."""
        
        if tool == "system_telemetry":
            if re.search(r"\b(memory|ram)\b", text):
                return {"metric": "memory"}
            if re.search(r"\bcpu\b", text):
                return {"metric": "cpu"}
            if re.search(r"\bdisk\b", text):
                return {"metric": "disk"}
            if re.search(r"\bbattery\b", text):
                return {"metric": "battery"}

        elif tool == "hardware_controls":
            num_match = re.search(r"\b(\d{1,3})\b", text)
            if "mute" in text and not num_match:
                return {"target": "mute", "value": 1}
            if num_match:
                val = int(num_match.group(1))
                if 0 <= val <= 100:
                    if re.search(r"\b(brightness|screen|backlight)\b", text):
                        return {"target": "brightness", "value": val}
                    if re.search(r"\b(volume|audio|speaker)\b", text):
                        return {"target": "volume", "value": val}

        elif tool == "app_lifecycle":
            if re.search(r"\b(list|running|processes)\b", text):
                return {"action": "list_running"}
            if re.search(r"\b(launch|open)\b", text):
                for app in ["vscode", "browser", "terminal", "calculator"]:
                    if app in text:
                        return {"action": "launch", "app_name": app}
            pid_match = re.search(r"\bpid\s*(\d+)\b", text)
            if "kill" in text and pid_match:
                return {"action": "request_kill", "pid": int(pid_match.group(1))}

        elif tool == "workspace_fs":
            if re.search(r"\blist\b", text) and not re.search(r"\b(write|save|read|search)\b", text):
                return {"action": "list", "relative_path": ""}
            read_match = re.search(r"\bread\s+([a-zA-Z0-9_.\-/]+)", text)
            if read_match:
                return {"action": "read_text", "relative_path": read_match.group(1)}

        elif tool == "power_session":
            if "lock" in text:
                return {"action": "lock_screen"}
            if "sleep" in text:
                return {"action": "sleep"}
            if re.search(r"\b(restart|reboot)\b", text):
                return {"action": "restart"}
            if re.search(r"\b(shutdown|shut down|power off)\b", text):
                return {"action": "shutdown"}
        
        return None

    def classify(self, prompt: str) -> IntentDecision:
        start = time.perf_counter()
        text = prompt.lower().strip()


        # 0. Catch time/date queries so it doesn't accidentally lock the screen!
        if re.search(r"\b(time|date|clock|what.*time)\b", text):
            elapsed = round((time.perf_counter() - start) * 1000, 3)
            return IntentDecision(
                route="DIRECT_MCP_BYPASS",
                target_agent="mcp_direct",
                matched_tools=[],
                extracted_args={"action": "get_time"},
                confidence=0.99,
                latency_ms=elapsed,
                reason="Time query detected -> Handled locally."
            )

        
        # 1. Check Agent 2 (RAG & Health Report)
        rag_hits = sum(1 for pat in self.RAG_PATTERNS if re.search(pat, text))
        if rag_hits > 0:
            elapsed = round((time.perf_counter() - start) * 1000, 3)
            return IntentDecision(
                route="DIRECT_RAG_AGENT",
                target_agent="agent2_rag",
                matched_tools=["system_telemetry", "workspace_fs"],
                extracted_args=None,
                confidence=0.95,
                latency_ms=elapsed,
                reason="RAG / Health Report intent -> Bypassing Agent 1 straight to Agent 2."
            )

        # 2. Match MCP tools
        matched_tools = [
            tool for tool, patterns in self.TOOL_PATTERNS.items()
            if any(re.search(pat, text) for pat in patterns)
        ]
        has_conjunction = any(re.search(pat, text) for pat in self.MULTI_STEP_CONJUNCTIONS)

        # 3. Single Tool Matched -> Try Deterministic Zero-LLM Extraction first!
        if len(matched_tools) == 1 and not has_conjunction:
            tool = matched_tools[0]
            extracted = self._try_extract_args(tool, text)
            elapsed = round((time.perf_counter() - start) * 1000, 3)

            if extracted is not None:
                return IntentDecision(
                    route="DIRECT_MCP_BYPASS",
                    target_agent="mcp_direct",
                    matched_tools=[tool],
                    extracted_args=extracted,
                    confidence=0.99,
                    latency_ms=elapsed,
                    reason=f"Deterministic extraction succeeded -> Calling MCP '{tool}' directly (0 LLM calls!)."
                )

            return IntentDecision(
                route="FAST_SINGLE_TOOL",
                target_agent="agent1_router",
                matched_tools=[tool],
                extracted_args=None,
                confidence=0.85,
                latency_ms=elapsed,
                reason=f"Matched '{tool}' but phrasing needs LLM parameter extraction -> Using pruned 1-tool GBNF."
            )

        # 4. Multi-step or ambiguous fallback
        elapsed = round((time.perf_counter() - start) * 1000, 3)
        if len(matched_tools) > 1 or has_conjunction:
            return IntentDecision(
                route="MULTI_STEP_PLANNER",
                target_agent="agent1_router",
                matched_tools=matched_tools or list(self.TOOL_PATTERNS.keys()),
                extracted_args=None,
                confidence=0.88,
                latency_ms=elapsed,
                reason="Compound multi-tool request -> Routing to Agent 1 Multi-Step Planner."
            )

        return IntentDecision(
            route="FAST_SINGLE_TOOL",
            target_agent="agent1_router",
            matched_tools=list(self.TOOL_PATTERNS.keys()),
            extracted_args=None,
            confidence=0.60,
            latency_ms=elapsed,
            reason="Ambiguous request -> Falling back to full LLM router."
        )