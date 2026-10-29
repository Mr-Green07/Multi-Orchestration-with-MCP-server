import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from fastmcp import Client
from llama_cpp import Llama
from mcp_server.server import mcp

WORKSPACE_DIR = Path(__file__).resolve().parent.parent / "workspace"

class WorkspaceRAGEngine:
    """Zero-VRAM BM25 lexical retriever over sandboxed workspace documents."""

    def __init__(self, workspace_dir: Path = WORKSPACE_DIR, chunk_size: int = 400):
        self.workspace_dir = workspace_dir
        self.chunk_size = chunk_size
        self.chunks: list[dict[str, Any]] = []

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower())

    def index_workspace(self) -> int:
        """Scan workspace for readable documents and split into chunks."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.chunks.clear()

        allowed_exts = {".txt", ".md", ".json", ".log", ".csv"}
        for file_path in self.workspace_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in allowed_exts:
                # Skip previously generated output reports so we don't self-loop
                if file_path.name.startswith("health_report"):
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    # Chunk by character window with light overlap
                    step = max(100, self.chunk_size - 50)
                    for i in range(0, len(text), step):
                        snippet = text[i : i + self.chunk_size]
                        self.chunks.append({
                            "source": file_path.relative_to(self.workspace_dir).as_posix(),
                            "text": snippet,
                            "tokens": self._tokenize(snippet),
                        })
                except Exception:
                    continue
        return len(self.chunks)


    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, str]]:
        """Retrieve top_k most relevant document chunks using BM25 scoring."""
        if not self.chunks:
            self.index_workspace()
        if not self.chunks:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return [{"source": c["source"], "text": c["text"]} for c in self.chunks[:top_k]]

        N = len(self.chunks)
        avgdl = sum(len(c["tokens"]) for c in self.chunks) / max(1, N)
        k1, b = 1.5, 0.75

        # Document frequency per query term
        df = {
            qt: sum(1 for c in self.chunks if qt in c["tokens"])
            for qt in set(query_tokens)
        }

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self.chunks:
            score = 0.0
            counts = Counter(chunk["tokens"])
            dl = len(chunk["tokens"])
            for qt in query_tokens:
                if counts[qt] == 0:
                    continue
                idf = math.log(1 + (N - df[qt] + 0.5) / (df[qt] + 0.5))
                tf = counts[qt]
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * (dl / max(1, avgdl)))
                score += idf * (numerator / denominator)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Fallback to first chunks if no exact keyword overlap
        if not scored:
            return [{"source": c["source"], "text": c["text"]} for c in self.chunks[:top_k]]

        return [{"source": item[1]["source"], "text": item[1]["text"]} for item in scored[:top_k]]



class RAGReportAgent:
    """
    Agent 2: Reads workspace reference documents via RAG, combines them with live
    system telemetry from Agent 1 / MCP Server, and writes a health report to workspace.
    """

    def __init__(self, shared_llm: Llama):
        self.llm = shared_llm
        self.rag = WorkspaceRAGEngine()

    async def gather_full_telemetry(self, client: Client) -> dict[str, Any]:
        """Collect CPU, Memory, Disk, and Battery snapshots via MCP tools."""
        stats: dict[str, Any] = {}
        for metric in ["cpu", "memory", "disk", "battery"]:
            res = await client.call_tool("system_telemetry", {"metric": metric})
            stats[metric] = res.data.get("payload", {})
        return stats

    async def generate_and_save_health_report(
        self,
        query: str = "system health baseline thresholds guidelines",
        output_filename: str = "health_report.md",
        prefetched_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run RAG retrieval + telemetry analysis and save report via MCP workspace_fs."""
        async with Client(mcp) as client:
            # 1. Obtain system stats (either passed from Agent 1 or gathered fresh)
            live_stats = prefetched_stats or await self.gather_full_telemetry(client)

            # 2. Index and retrieve relevant workspace documents via RAG
            num_chunks = self.rag.index_workspace()
            retrieved_docs = self.rag.retrieve(query, top_k=2)

            if retrieved_docs:
                rag_context = "\n\n".join(
                    f"]\n{d['text']}" for d in retrieved_docs
                )
            else:
                rag_context = "No custom baseline documents found in workspace. Use standard OS health thresholds (CPU < 80%, Memory < 85%, Disk < 90%)."

            # 3. Prompt shared Qwen 4B model to synthesize structured health evaluation
            schema = {
                "type": "object",
                "properties": {
                    "overall_status": {"type": "string", "enum": ["HEALTHY", "WARNING", "CRITICAL"]},
                    "executive_summary": {"type": "string"},
                    "findings": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "recommendations": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["overall_status", "executive_summary", "findings", "recommendations"],
                "additionalProperties": False
            }

            system_msg = (
                "You are a System Health Analyst Agent. Compare the Live System Telemetry against "
                "the Retrieved Workspace Reference Documents and output a JSON health evaluation."
            )
            user_msg = (
                f"Retrieved Workspace Documents:\n{rag_context}\n\n"
                f"Live System Telemetry:\n{json.dumps(live_stats)}\n\n"
                f"User Focus: {query}"
            )

            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                response_format={"type": "json_object", "schema": schema},
            )

            raw_eval = response["choices"][0]["message"]["content"]
            eval_data = json.loads(raw_eval)

            # 4. Format clean Markdown report
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sources_list = list({d["source"] for d in retrieved_docs}) or ["Standard OS Defaults"]
            findings_md = "\n".join(f"- {item}" for item in eval_data.get("findings", []))
            recs_md = "\n".join(f"- {item}" for item in eval_data.get("recommendations", []))

            markdown_report = (
                f"# System Diagnostic & Health Report\n"
                f"**Generated:** {timestamp}  \n"
                f"**Overall Status:** `{eval_data['overall_status']}`  \n"
                f"**RAG Reference Sources:** {', '.join(sources_list)}\n\n"
                f"## Executive Summary\n{eval_data['executive_summary']}\n\n"
                f"## Key Findings\n{findings_md}\n\n"
                f"## Recommendations\n{recs_md}\n\n"
                f"## Raw Telemetry Snapshot\n```json\n{json.dumps(live_stats, indent=2)}\n```\n"
            )

            # 5. Write report into sandboxed workspace using MCP workspace_fs tool
            write_res = await client.call_tool(
                "workspace_fs",
                {
                    "action": "write_text",
                    "relative_path": output_filename,
                    "content": markdown_report,
                },
            )

            return {
                "status": write_res.data.get("status", "success"),
                "metric_or_action": "rag_health_report",
                "summary": f"[{eval_data['overall_status']}] {eval_data['executive_summary']} (Saved to workspace/{output_filename})",
                "payload": {
                    "report_file": output_filename,
                    "overall_status": eval_data["overall_status"],
                    "indexed_chunks": num_chunks,
                    "rag_sources_used": sources_list,
                    "evaluation": eval_data,
                },
            }