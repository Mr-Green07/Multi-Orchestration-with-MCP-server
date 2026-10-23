import os 
from pathlib import Path 
from typing import Literal, Optional
from mcp_server.schemas import SystemToolResponse

JAIL_ROOT = Path(__file__).resolve().parent.parent.parent / "new_workspace"

def execute_workspace_fs(   #search for file and folder inside the sandboxing directory later we will add creating command and not provide to delete the file and folder
    action: Literal["List", "read_text", "search"],
    relative_path: str = "",
    search_query: Optional[str] = None
) -> dict: # type: ignore
    try:
        JAIL_ROOT.mkdir(parents=True, exist_ok=True) #check for the path is exists
        target_path = (JAIL_ROOT / relative_path).resolve()

        if not target_path.is_relative_to(JAIL_ROOT): #if target is not related to jail root return denied access
            return SystemToolResponse(
                status="error",
                metric_or_action="workspace_fs",
                summary="Security violation: Path traversal outside workspace jail is forbidden.",
                payload={"error": "Access denied"}
            ).model_dump()


        if action == "list": #list all files inside the directory
            if not target_path.exists():
                return SystemToolResponse(
                    status="error",
                    metric_or_action="list_workspace",
                    summary="The specified path does not exist in the workspace.",
                    payload={"error": "Path not found"}
                ).model_dump()

            items = [] #list containing all files 
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
            
            content = target_path.read_text(encoding="utf-8", errors="ignore") #stores the content of text file 
            if len(content) > 4000:
                content = content[:4000] + "\n[Content truncated due to length...]"  #read if file words is less than 4000 words

            return SystemToolResponse(
                status="success",
                metric_or_action="read_text",
                summary=f"Successfully read file {target_path.name}.",
                payload={"filename": target_path.name, "content": content}
            ).model_dump()
        
        elif action == "search": #it will search for whole directory for the query provided
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
        else:
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