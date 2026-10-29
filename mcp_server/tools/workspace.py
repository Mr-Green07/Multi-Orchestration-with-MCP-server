from pathlib import Path
from typing import Literal, Optional
from mcp_server.schemas import SystemToolResponse

JAIL_ROOT = Path(__file__).resolve().parent.parent.parent / "workspace"

def execute_workspace_fs(
    action: Literal["list", "read_text", "write_text", "search"],
    relative_path: str = "",
    search_query: Optional[str] = None,
    content: Optional[str] = None
) -> dict:
    """
    Safely inspect, read, write, or search files within the sandboxed workspace folder.
    USE WHEN user asks to check files, read documents, save/write text, or search in workspace.
    """
    try:
        JAIL_ROOT.mkdir(parents=True, exist_ok=True)
        target_path = (JAIL_ROOT / relative_path).resolve()

        if not target_path.is_relative_to(JAIL_ROOT):
            return SystemToolResponse(
                status="error",
                metric_or_action="workspace_fs",
                summary="Security violation: Path traversal outside workspace jail is forbidden.",
                payload={"error": "Access denied"}
            ).model_dump()

        if action == "list":
            if not target_path.exists():
                return SystemToolResponse(
                    status="error",
                    metric_or_action="list_workspace",
                    summary="The specified path does not exist in the workspace.",
                    payload={"error": "Path not found"}
                ).model_dump()

            items = []
            if target_path.is_dir():
                for item in target_path.iterdir():
                    items.append({
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size_bytes": item.stat().st_size if item.is_file() else None
                    })
            return SystemToolResponse(
                status="success",
                metric_or_action="list_workspace",
                summary=f"Listed {len(items)} items from workspace path.",
                payload={"items": items}
            ).model_dump()

        elif action == "read_text":
            if not target_path.is_file():
                return SystemToolResponse(
                    status="error",
                    metric_or_action="read_text",
                    summary="The specified path is not a valid file.",
                    payload={"error": "Not a file"}
                ).model_dump()

            file_content = target_path.read_text(encoding="utf-8", errors="ignore")
            if len(file_content) > 2000:
                file_content = file_content[:2000] + "\n[Truncated...]"

            return SystemToolResponse(
                status="success",
                metric_or_action="read_text",
                summary=f"Successfully read file {target_path.name}.",
                payload={"filename": target_path.name, "content": file_content}
            ).model_dump()

        elif action == "write_text":
            if not relative_path or target_path.is_dir():
                return SystemToolResponse(
                    status="error",
                    metric_or_action="write_text",
                    summary="A valid relative file path is required for write_text.",
                    payload={"error": "Invalid filename"}
                ).model_dump()
            if content is None:
                return SystemToolResponse(
                    status="error",
                    metric_or_action="write_text",
                    summary="Missing 'content' parameter for write_text.",
                    payload={"error": "content required"}
                ).model_dump()

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            return SystemToolResponse(
                status="success",
                metric_or_action="write_text",
                summary=f"Successfully wrote {len(content)} characters to {target_path.name}.",
                payload={"filename": target_path.name, "bytes_written": len(content)}
            ).model_dump()

        elif action == "search":
            if not search_query:
                return SystemToolResponse(
                    status="error",
                    metric_or_action="search_workspace",
                    summary="Missing 'search_query' parameter for search action.",
                    payload={"error": "search_query required"}
                ).model_dump()

            matches = []
            for file_path in JAIL_ROOT.rglob("*"):
                if file_path.is_file():
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")
                        if search_query.lower() in text.lower():
                            matches.append(file_path.relative_to(JAIL_ROOT).as_posix())
                    except Exception:
                        continue

            return SystemToolResponse(
                status="success",
                metric_or_action="search_workspace",
                summary=f"Found '{search_query}' in {len(matches)} files.",
                payload={"matches": matches}
            ).model_dump()

        return SystemToolResponse(
            status="error",
            metric_or_action="workspace_fs",
            summary="Unsupported workspace action.",
            payload={"error": "Invalid action"}
        ).model_dump()

    except Exception as e:
        return SystemToolResponse(
            status="error",
            metric_or_action="workspace_fs",
            summary="Failed to execute workspace filesystem operation.",
            payload={"error": str(e)}
        ).model_dump()