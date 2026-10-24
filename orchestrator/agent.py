import asyncio
import json
from pathlib import Path
from llama_cpp import Llama
from fastmcp import Client
from mcp_server.server import mcp

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "Qwen3.5-4BQ" / "model.gguf"

class SystemAgentOrchestrator:
    def __init__(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"GGUF model not found at: {MODEL_PATH}")

        print(f"Loading model from {MODEL_PATH.name} (optimized for low RAM/VRAM)...")
        self.llm = Llama(
            model_path=str(MODEL_PATH),
            n_gpu_layers=-1,      # Offload to GPU
            n_ctx=1024,           # Tight context window to save RAM/VRAM
            n_batch=256,          # Smaller batch buffer to reduce memory spike
            use_mmap=True,        # Memory-map weights from disk instead of duplicating in RAM
            verbose=False
        )

    async def get_compact_tool_prompt(self, client: Client) -> tuple[str, dict]:
        """Build a concrete example-driven prompt and dynamic JSON schema from FastMCP tools."""
        tools = await client.list_tools()
        tool_lines = []
        one_of_schemas = []

        for t in tools:
            schema = t.input_schema # type: ignore
            props = schema.get("properties", {})
            
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

            # Resolve $defs if present inside tool schema (e.g., AllowedApps Enum)
            tool_branch = {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "const": t.name},
                    "arguments": schema
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False
            }
            one_of_schemas.append(tool_branch)

        dynamic_grammar_schema = {
            "type": "object",
            "oneOf": one_of_schemas
        }

        prompt = (
            "You are a system tool router. Convert the user request into a JSON tool call.\n"
            "Never invent argument names. Use ONLY the exact argument names and allowed values listed below.\n\n"
            + "\n\n".join(tool_lines)
            + "\n\nExample Valid Output:\n"
            '{"tool": "system_telemetry", "arguments": {"metric": "memory"}}'
        )
        return prompt, dynamic_grammar_schema

    async def execute_query(self, user_prompt: str) -> dict:
        """Route user query through Qwen 3.5 4B -> FastMCP Tool -> Output."""
        async with Client(mcp) as client:
            system_prompt, grammar_schema = await self.get_compact_tool_prompt(client)

            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                response_format={
                    "type": "json_object",
                    "schema": grammar_schema
                }
            )

            raw_content = response["choices"][0]["message"]["content"] # type: ignore
            print(f"\n[Model Decision]: {raw_content}")

            try:
                decision = json.loads(raw_content) # type: ignore
                tool_name = decision.get("tool")
                tool_args = decision.get("arguments", {})

                tool_result = await client.call_tool(tool_name, tool_args)
                data = tool_result.data

                # Tier 3 Guardrail: Intercept requires_confirmation responses
                # if data.get("status") == "requires_confirmation":
                #     print(f"\n⚠️  [SECURITY GATE]: {data.get('summary')}")
                #     print(f"⚠️  [WARNING]: {data.get('payload', {}).get('warning')}")
                #     confirm = input("Approve destructive action? (y/N): ").strip().lower()
                #     if confirm == "y":
                #         data["status"] = "confirmed_by_user"
                #         data["summary"] = f"User approved action: {data.get('metric_or_action')}"
                #     else:
                #         data["status"] = "cancelled"
                #         data["summary"] = f"Action '{data.get('metric_or_action')}' aborted by user."
                # Tier 3 Guardrail: Intercept requires_confirmation responses
                if data.get("status") == "requires_confirmation":
                    token = data.get("confirmation_token")
                    print(f"\n⚠️  [SECURITY GATE]: {data.get('summary')}")
                    print(f"⚠️  [WARNING]: {data.get('payload', {}).get('warning')}")
                    confirm = input("Approve destructive action? (y/N): ").strip().lower()
                    if confirm == "y" and token:
                        tool_args["confirmation_token"] = token
                        confirmed_result = await client.call_tool(tool_name, tool_args)
                        return confirmed_result.data
                    else:
                        data["status"] = "cancelled"
                        data["summary"] = f"Action '{data.get('metric_or_action')}' aborted by user."
                return data

            except Exception as e:
                return {
                    "status": "error",
                    "summary": f"Orchestrator failed to parse or execute tool: {str(e)}",
                    "raw_model_output": raw_content
                }

async def interactive_loop():
    agent = SystemAgentOrchestrator()
    print("\n=======================================================")
    print("🤖 System Operator Agent Online (Type 'exit' to quit)")
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
            print(f"[Result ({result.get('status')})]: {result.get('summary')}")
            print(f"[Payload]: {json.dumps(result.get('payload', {}), indent=2)}")

        except KeyboardInterrupt:
            print("\nExiting...")
            break

if __name__ == "__main__":
    asyncio.run(interactive_loop())