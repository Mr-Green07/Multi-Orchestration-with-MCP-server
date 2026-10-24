import asyncio
import json
from pathlib import Path
from llama_cpp import Llama
from fastmcp import Client
from mcp_server.server import mcp

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "Qwen3.5-4BQ" / "model.gguf"

# Strict JSON Schema that forces llama.cpp to only output valid tool calls
TOOL_CALL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "enum": [
                "system_telemetry",
                "hardware_controls",
                "app_lifecycle",
                "workspace_fs",
                "power_session"
            ]
        },
        "arguments": {
            "type": "object"
        }
    },
    "required": ["tool", "arguments"],
    "additionalProperties": False
}

class SystemAgentOrchestrator:
    def __init__(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"GGUF model not found at: {MODEL_PATH}")

        print(f"Loading model from {MODEL_PATH.name}...")
        self.llm = Llama(
            model_path=str(MODEL_PATH),
            n_gpu_layers=-1,
            n_ctx=2048,
            n_batch=512,
            verbose=False
        )

    async def get_compact_tool_prompt(self, client: Client) -> tuple[str, dict]:
        """Build a concrete example-driven prompt and dynamic JSON schema from FastMCP tools."""
        tools = await client.list_tools()
        tool_lines = []
        one_of_schemas = []

        for t in tools:
            schema = t.input_schema
            props = schema.get("properties", {})
            
            # Build clean human-readable signature for the 4B model
            arg_examples = {}
            for k, v in props.items():
                if "enum" in v:
                    arg_examples[k] = " | ".join(str(x) for x in v["enum"])
                elif "anyOf" in v:
                    # Handle Optional Enums/Types
                    sub_types = [sub.get("type") for sub in v["anyOf"] if sub.get("type") != "null"]
                    arg_examples[k] = f"optional ({'/'.join(filter(None, sub_types))})"
                else:
                    arg_examples[k] = v.get("type", "any")

            tool_lines.append(
                f"Tool: {t.name}\n"
                f"  Description: {t.description}\n"
                f"  Exact Arguments Schema: {json.dumps(arg_examples)}"
            )

            # Build per-tool strict grammar branch so arguments MUST match the tool's exact inputSchema
            one_of_schemas.append({
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "const": t.name},
                    "arguments": schema
                },
                "required": ["tool", "arguments"],
                "additionalProperties": False
            })

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
                    "schema": grammar_schema  # Enforces exact FastMCP Pydantic schema at token level!
                }
            )

            raw_content = response["choices"][0]["message"]["content"] # type: ignore
            print(f"[Model Decision]: {raw_content}")

            try:
                decision = json.loads(raw_content) # type: ignore
                tool_name = decision.get("tool")
                tool_args = decision.get("arguments", {})

                tool_result = await client.call_tool(tool_name, tool_args)
                return tool_result.data

            except Exception as e:
                return {
                    "status": "error",
                    "summary": f"Orchestrator failed to parse or execute tool: {str(e)}",
                    "raw_model_output": raw_content
                }

async def main():
    agent = SystemAgentOrchestrator()
    
    print("\n--- Testing Query: 'How much memory is my system using?' ---")
    result = await agent.execute_query("How much memory is my system using right now?")
    print(f"[MCP Server Result]: {json.dumps(result, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())