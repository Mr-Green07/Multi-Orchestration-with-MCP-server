import asyncio
import json
from pathlib import Path
import os
import sys
from pathlib import Path

# Ensure Windows can locate CUDA / llama.cpp dependent DLLs before importing llama_cpp
if sys.platform == "win32":
    venv_base = Path(sys.prefix) / "Lib" / "site-packages"
    for dll_dir in [
        venv_base / "llama_cpp" / "lib",
        venv_base / "nvidia" / "cuda_runtime" / "bin",
        venv_base / "nvidia" / "cublas" / "bin",
    ]:
        if dll_dir.exists():
            os.add_dll_directory(str(dll_dir))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")

from llama_cpp import Llama
from fastmcp import Client
from mcp_server.server import mcp
from orchestrator.rag_agent import RAGReportAgent
from orchestrator.intent_classifier import FastIntentClassifier



MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "Qwen3.5-4BQ" / "model.gguf"

class SystemAgentOrchestrator:
    def __init__(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"GGUF model not found at: {MODEL_PATH}")

        print(f"Loading model from {MODEL_PATH.name} (optimized for low RAM/VRAM)...")
        self.llm = Llama(
            model_path=str(MODEL_PATH),
            n_gpu_layers=-1,
            n_ctx=1024,
            n_batch=256,
            use_mmap=True,
            verbose=False
        )
        self.rag_agent = RAGReportAgent(shared_llm=self.llm)
        self.classifier = FastIntentClassifier()
        self.rag_agent = RAGReportAgent(shared_llm=self.llm)

    async def get_compact_tool_prompt(
        self, client: Client, allowed_tools: list[str] | None = None, include_finish: bool = False
    ) -> tuple[str, dict]:
        """Build a pruned prompt and GBNF schema containing ONLY the tools matched by the Intent Classifier."""
        tools = await client.list_tools()
        tool_lines = []
        one_of_schemas = []

        for t in tools:
            if allowed_tools and t.name not in allowed_tools:
                continue  # Prune irrelevant tools to save ~75% prefill tokens!
            schema = t.input_schema
            props = schema.get("properties", {})
            # ... (keep your existing loop body for arg_examples and one_of_schemas) ...
            arg_examples = {}
            for k, v in props.items():
                if "enum" in v:
                    arg_examples[k] = " | ".join(str(x) for x in v["enum"])
                elif "anyOf" in v:
                    sub_types = [sub.get("type") for sub in v["anyOf"] if sub.get("type") != "null"]
                    arg_examples[k] = f"optional ({'/'.join(filter(None, sub_types))})"
                else:
                    arg_examples[k] = v.get("type", "any")

            tool_lines.append(
                f"Tool: {t.name}\n"
                f"  Description: {t.description}\n"
                f"  Exact Arguments Schema: {json.dumps(arg_examples)}"
            )

            one_of_schemas.append({
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "const": t.name},
                    "arguments": schema
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False
            })



        # Add virtual delegation route to Agent 2 (RAG & Health Report Agent)
        tool_lines.append(
            "Tool: generate_health_report\n"
            "  Description: Delegate to RAG Agent to read workspace guidelines/docs, analyze live system stats, and write a health report.\n"
            '  Exact Arguments Schema: {"query": "string", "output_filename": "string"}'
        )
        one_of_schemas.append({
            "type": "object",
            "properties": {
                "tool": {"type": "string", "const": "generate_health_report"},
                "arguments": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "output_filename": {"type": "string"}
                    },
                    "required": ["query", "output_filename"],
                    "additionalProperties": False
                }
            },
            "required": ["tool", "arguments"],
            "additionalProperties": False
        })


        # Add virtual 'finish' tool for multi-step completion
        tool_lines.append(
            "Tool: finish\n"
            "  Description: Call this ONLY when all parts of the user request have been completed.\n"
            '  Exact Arguments Schema: {"final_summary": "string"}'
        )
        one_of_schemas.append({
            "type": "object",
            "properties": {
                "tool": {"type": "string", "const": "finish"},
                "arguments": {
                    "type": "object",
                    "properties": {"final_summary": {"type": "string"}},
                    "required": ["final_summary"],
                    "additionalProperties": False
                }
            },
            "required": ["tool", "arguments"],
            "additionalProperties": False
        })

        dynamic_grammar_schema = {
            "type": "object",
            "oneOf": one_of_schemas
        }

        prompt = (
            "You are a multi-step system tool router. Convert the user request into the NEXT required JSON tool call.\n"
            "If previous steps are shown, do NOT repeat them—execute the next uncompleted action, or call 'finish' if everything requested is done.\n\n"
            + "\n\n".join(tool_lines)
        )
        return prompt, dynamic_grammar_schema

    async def execute_query(self, user_prompt: str, max_steps: int = 3) -> dict:
        """Execute 1 to max_steps chained tool calls to fulfill the user prompt."""
        intent = self.classifier.classify(user_prompt)
        print(
            f"\n⚡ [Intent Classifier ({intent.latency_ms}ms)]: Route={intent.route} "
            f"| Target={intent.target_agent} | Tools={intent.matched_tools}"
        )


        if intent.route == "DIRECT_MCP_BYPASS" and intent.extracted_args and "action" in intent.extracted_args and intent.extracted_args["action"] == "get_time":
            from datetime import datetime
            current_t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"🕒 [Local Timekeeper]: Current system time is {current_t}")
            return {
                "status": "success",
                "metric_or_action": "get_time",
                "summary": f"Current system time is {current_t}",
                "payload": {"time": current_t}
            }
        
        # FAST-PATH 0: ZERO-LLM DIRECT MCP EXECUTION (~5ms total!)
        if intent.route == "DIRECT_MCP_BYPASS" and intent.extracted_args is not None:
            tool_name = intent.matched_tools[0]
            tool_args = intent.extracted_args
            print(f"🚀 [Zero-LLM Bypass]: Calling FastMCP {tool_name}({json.dumps(tool_args)}) directly!")

            async with Client(mcp) as client:
                tool_result = await client.call_tool(tool_name, tool_args)
                data = tool_result.data

                # Still enforce Tier 3 Confirmation Gate even on Direct Bypass!
                if data.get("status") == "requires_confirmation":
                    token = data.get("confirmation_token")
                    print(f"\n⚠️  [SECURITY GATE]: {data.get('summary')}")
                    print(f"⚠️  [WARNING]: {data.get('payload', {}).get('warning')}")
                    confirm = input("Approve destructive action? (y/N): ").strip().lower()
                    if confirm == "y" and token:
                        tool_args["confirmation_token"] = token
                        confirmed_result = await client.call_tool(tool_name, tool_args)
                        data = confirmed_result.data
                    else:
                        data["status"] = "cancelled"
                        data["summary"] = f"Action '{data.get('metric_or_action')}' aborted by user."
                return data

        # FAST-PATH 1: Direct handoff to Agent 2 (RAG)
        if intent.route == "DIRECT_RAG_AGENT":
            print("🚀 [RAG Fast-Path]: Bypassing Agent 1 -> Direct dispatch to Agent 2 (RAGReportAgent)...")
            return await self.rag_agent.generate_and_save_health_report(query=user_prompt)
        # Fast-Path 2: Single tool vs Multi-step loop
        effective_max_steps = 1 if intent.route == "FAST_SINGLE_TOOL" else max_steps
        include_finish = intent.route == "MULTI_STEP_PLANNER"
        async with Client(mcp) as client:
            system_prompt, grammar_schema = await self.get_compact_tool_prompt(
                client, 
                allowed_tools=intent.matched_tools,
                include_finish=include_finish
            )
            scratchpad: list[str] = []
            steps_taken: list[dict] = []
            last_result: dict = {}

            for step_idx in range(1, max_steps + 1):
                if scratchpad:
                    history_text = "\n".join(scratchpad)
                    current_user_msg = (
                        f"Original Request: {user_prompt}\n\n"
                        f"Completed Steps So Far:\n{history_text}\n\n"
                        "What is the next tool call? (Call 'finish' if the request is already satisfied)."
                    )
                else:
                    current_user_msg = user_prompt

                response = self.llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": current_user_msg}
                    ],
                    temperature=0.0,
                    response_format={
                        "type": "json_object",
                        "schema": grammar_schema
                    }
                )

                raw_content = response["choices"][0]["message"]["content"]
                print(f"\n[Step {step_idx} Model Decision]: {raw_content}")

                try:
                    decision = json.loads(raw_content)
                    tool_name = decision.get("tool")
                    tool_args = decision.get("arguments", {})

                    # Check if the model signaled completion
                    if tool_name == "finish":
                        return {
                            "status": "success",
                            "metric_or_action": "multi_step_complete",
                            "summary": tool_args.get("final_summary", last_result.get("summary", "Completed.")),
                            "payload": last_result.get("payload", {}),
                            "steps": steps_taken
                        }
                    # Check if Agent 1 is delegating to Agent 2 (RAG Report Agent)
                    if tool_name == "generate_health_report":
                        print("\n🔄 [Multi-Agent Handoff]: Agent 1 -> Agent 2 (RAG & Health Report Agent)...")
                        rag_result = await self.rag_agent.generate_and_save_health_report(
                            query=tool_args.get("query", user_prompt),
                            output_filename=tool_args.get("output_filename", "health_report.md"),
                            prefetched_stats=last_result.get("payload") if last_result else None
                        )
                        rag_result["steps"] = steps_taken + [{"step": step_idx, "tool": "rag_agent", "result": rag_result}]
                        return rag_result

                    tool_result = await client.call_tool(tool_name, tool_args)
                    data = tool_result.data

                    # Tier 3 Guardrail: Intercept requires_confirmation responses
                    if data.get("status") == "requires_confirmation":
                        token = data.get("confirmation_token")
                        print(f"\n⚠️  [SECURITY GATE]: {data.get('summary')}")
                        print(f"⚠️  [WARNING]: {data.get('payload', {}).get('warning')}")
                        confirm = input("Approve destructive action? (y/N): ").strip().lower()
                        if confirm == "y" and token:
                            tool_args["confirmation_token"] = token
                            confirmed_result = await client.call_tool(tool_name, tool_args)
                            data = confirmed_result.data
                        else:
                            data["status"] = "cancelled"
                            data["summary"] = f"Action '{data.get('metric_or_action')}' aborted by user."
                            return data

                    last_result = data
                    steps_taken.append({"step": step_idx, "tool": tool_name, "result": data})

                    # Compress observation for the next step's scratchpad
                    compact_obs = json.dumps(data.get("payload", {}))[:300]
                    scratchpad.append(
                        f"Step {step_idx}: Called {tool_name}({json.dumps(tool_args)}) -> Status: {data.get('status')}, Output: {compact_obs}"
                    )

                    # Fast-exit optimization: If the user prompt doesn't contain multi-step conjunctions, return immediately
                    lower_prompt = user_prompt.lower()
                    if not any(word in lower_prompt for word in [" and ", " then ", " save ", " write ", " after "]):
                        data["steps"] = steps_taken
                        return data

                except Exception as e:
                    return {
                        "status": "error",
                        "summary": f"Orchestrator failed at step {step_idx}: {str(e)}",
                        "raw_model_output": raw_content
                    }

            # Reached max_steps; return the final accumulated result
            last_result["steps"] = steps_taken
            return last_result

async def interactive_loop():
    agent = SystemAgentOrchestrator()
    print("\n=======================================================")
    print("🤖 Multi-Step System Agent Online (Type 'exit' to quit)")
    print("=======================================================")

    while True:
        try:
            user_input = input("\nYou > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("Shutting down agent...")
                break

            result = await agent.execute_query(user_input)
            print(f"\n[Final Status ({result.get('status')})]: {result.get('summary')}")
            if "steps" in result and len(result["steps"]) > 1:
                print(f"[Chained Steps Executed]: {len(result['steps'])}")
            print(f"[Payload]: {json.dumps(result.get('payload', {}), indent=2)}")

        except KeyboardInterrupt:
            print("\nExiting...")
            break

if __name__ == "__main__":
    asyncio.run(interactive_loop())