"""mcp_server/tools/workspace.py
=============================
Sandboxed file access inside the one workspace jail (``config.WORKSPACE_JAIL_ROOT``).

Every action goes through :func:`resolve_in_jail`, which rejects absolute paths,
drive-qualified paths, UNC paths and traversal; the resolved path is then checked
with ``is_relative_to`` so symlink tricks are caught too.

Caps are deliberate: a directory listing, a search and a tree walk all have hard
limits, because an agent that can be made to scan the whole disk is a denial of
service against the user's own machine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import config
from mcp_server.security import create_confirmation_token, verify_and_consume_token
from mcp_server.tools._common import (
    SCOPE_INDEX,
    SCOPE_PREFIX,
    JailViolation,
    is_text_file,
    iter_jail_files,
    read_only_scopes,
    read_text_capped,
    resolve_in_jail,
    resolve_read_only,
    respond,
)

#: Actions that may reach a read-only scope. Writes never can.
READ_ONLY_ACTIONS = frozenset({"list", "read_text", "search", "stat", "tree"})

WorkspaceAction = Literal["list", "read_text", "search", "stat", "tree", "write_text"]


def _describe(path: Path) -> dict:
    root = Path(config.WORKSPACE_JAIL_ROOT).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    try:
        stat = path.stat()
        size = stat.st_size if path.is_file() else None
        mtime = int(stat.st_mtime)
    except OSError:
        size, mtime = None, None
    return {
        "name": path.name,
        "path": relative or ".",
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": size,
        "modified_epoch": mtime,
    }


def execute_workspace_fs(
    action: WorkspaceAction,
    relative_path: str = "",
    search_query: str | None = None,
    content: str | None = None,
    max_results: int = 20,
    confirmation_token: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    tool = "workspace_fs"
    arguments = {"action": action, "relative_path": relative_path,
                 "search_query": search_query, "max_results": max_results}

    # A leading '@' addresses an opt-in read-only scope outside the jail.
    if (relative_path or "").strip().startswith(SCOPE_PREFIX):
        if (relative_path or "").strip() == SCOPE_INDEX:
            scopes = read_only_scopes()
            return respond(
                tool=tool, action="list_scopes", status="success",
                summary=(f"{len(scopes)} read-only scope(s) configured."
                         if scopes else "No read-only scopes are configured."),
                payload={"scopes": [{"name": "@" + name, "path": str(path)}
                                    for name, path in scopes.items()],
                         "writable": False,
                         "configure_with": "AGENT_READ_ONLY_ROOTS"},
                arguments=arguments, correlation_id=correlation_id, applied=None)
        if action not in READ_ONLY_ACTIONS:
            return respond(
                tool=tool, action=f"{action}_workspace", status="error",
                summary=f"Scope paths are read-only; '{action}' is not allowed there.",
                payload={"code": "scope_read_only", "retryable": False,
                         "user_hint": "Write inside the workspace jail instead."},
                arguments=arguments, correlation_id=correlation_id, applied=False)
        try:
            target = resolve_read_only(relative_path)
        except JailViolation as exc:
            return respond(tool=tool, action=f"{action}_scope", status="error",
                           summary=str(exc),
                           payload={"code": "scope_violation", "retryable": False},
                           arguments=arguments, correlation_id=correlation_id)
        scope_name = (relative_path or "").strip()[len(SCOPE_PREFIX):].split("/")[0]
    else:
        try:
            target = resolve_in_jail(relative_path)
        except JailViolation as exc:
            return respond(tool=tool, action=f"{action}_workspace", status="error",
                           summary=str(exc),
                           payload={"code": "jail_violation", "error": "Access denied"},
                           arguments=arguments, correlation_id=correlation_id)
        scope_name = None

    # ------------------------------------------------------------------ list
    if action == "list":
        if not target.exists():
            return respond(tool=tool, action="list_workspace", status="error",
                           summary="The specified path does not exist in the workspace.",
                           payload={"code": "not_found"},
                           arguments=arguments, correlation_id=correlation_id)
        if not target.is_dir():
            return respond(tool=tool, action="list_workspace", status="error",
                           summary="The specified path is not a directory.",
                           payload={"code": "not_a_directory"},
                           arguments=arguments, correlation_id=correlation_id)
        entries = [_describe(child) for child in sorted(target.iterdir())
                   if child.name != ".gitkeep"][: config.MAX_LIST_ENTRIES]
        return respond(
            tool=tool, action="list_workspace", status="success",
            summary=f"Listed {len(entries)} items from workspace path.",
            payload={"directory": _describe(target)["path"], "items": entries,
                     "truncated": len(entries) >= config.MAX_LIST_ENTRIES,
                     "scope": scope_name, "writable": scope_name is None},
            arguments=arguments, correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------ stat
    if action == "stat":
        if not target.exists():
            return respond(tool=tool, action="stat", status="error",
                           summary="The specified path does not exist in the workspace.",
                           payload={"code": "not_found"},
                           arguments=arguments, correlation_id=correlation_id)
        return respond(tool=tool, action="stat", status="success",
                       summary=f"Described {target.name}.",
                       payload=_describe(target), arguments=arguments,
                       correlation_id=correlation_id)

    # ------------------------------------------------------------------ read
    if action == "read_text":
        if not target.is_file():
            return respond(tool=tool, action="read_text", status="error",
                           summary="The specified path is not a valid file.",
                           payload={"code": "not_a_file"},
                           arguments=arguments, correlation_id=correlation_id)
        if not is_text_file(target):
            return respond(tool=tool, action="read_text", status="error",
                           summary=f"Refusing to read '{target.suffix}' as text.",
                           payload={"code": "not_text"},
                           arguments=arguments, correlation_id=correlation_id)
        try:
            text, truncated = read_text_capped(target)
        except (ValueError, OSError) as exc:
            return respond(tool=tool, action="read_text", status="error",
                           summary=f"Failed to read file: {exc}",
                           payload={"code": "read_failed"},
                           arguments=arguments, correlation_id=correlation_id)
        return respond(tool=tool, action="read_text", status="success",
                       summary=f"Successfully read file {target.name}.",
                       payload={"filename": target.name, "content": text,
                                "truncated": truncated, "scope": scope_name,
                                "writable": scope_name is None},
                       arguments=arguments, correlation_id=correlation_id)

    # ------------------------------------------------------------------ search
    if action == "search":
        if not search_query:
            return respond(tool=tool, action="search_workspace", status="error",
                           summary="Missing 'search_query' parameter for search action.",
                           payload={"code": "missing_query"},
                           arguments=arguments, correlation_id=correlation_id)
        needle = search_query.lower()
        matches: list[dict] = []
        scanned = 0
        for path in iter_jail_files(Path(config.WORKSPACE_JAIL_ROOT).resolve()):
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle not in text.lower():
                continue
            first_line = next((i for i, line in enumerate(text.splitlines(), 1)
                               if needle in line.lower()), None)
            snippet = ""
            if first_line is not None:
                snippet = text.splitlines()[first_line - 1][:200]
            matches.append({
                "path": path.relative_to(Path(config.WORKSPACE_JAIL_ROOT).resolve()).as_posix(),
                "line": first_line,
                "snippet": snippet,
            })
            if len(matches) >= min(max_results, config.MAX_SEARCH_MATCHES):
                break
        return respond(
            tool=tool, action="search_workspace", status="success",
            summary=f"Found '{search_query}' in {len(matches)} files "
                    f"({scanned} scanned).",
            payload={"query": search_query, "matches": matches,
                     "files_scanned": scanned,
                     "truncated": len(matches) >= min(max_results, config.MAX_SEARCH_MATCHES)},
            arguments=arguments, correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------ tree
    if action == "tree":
        if not target.is_dir():
            return respond(tool=tool, action="tree", status="error",
                           summary="The specified path is not a directory.",
                           payload={"code": "not_a_directory"},
                           arguments=arguments, correlation_id=correlation_id)
        lines: list[str] = []
        count = 0
        for path in sorted(target.rglob("*")):
            depth = len(path.relative_to(target).parts)
            if depth > config.MAX_TREE_DEPTH:
                continue
            lines.append(f"{'  ' * (depth - 1)}{path.name}"
                         f"{'/' if path.is_dir() else ''}")
            count += 1
            if count >= config.MAX_LIST_ENTRIES:
                break
        return respond(tool=tool, action="tree", status="success",
                       summary=f"Rendered {count} entries.",
                       payload={"root": _describe(target)["path"], "tree": lines},
                       arguments=arguments, correlation_id=correlation_id)

    # ------------------------------------------------------------------ write
    if action == "write_text":
        if not content:
            return respond(tool=tool, action="write_text", status="error",
                           summary="Missing 'content' for write_text.",
                           payload={"code": "missing_content"},
                           arguments=arguments, correlation_id=correlation_id)
        if target.exists():
            expected = f"overwrite:{_describe(target)['path']}"
            if not confirmation_token or not verify_and_consume_token(
                    confirmation_token, expected_action=expected):
                token = create_confirmation_token(expected, {"path": str(target)})
                return respond(
                    tool=tool, action="write_text", status="requires_confirmation",
                    summary=f"'{target.name}' already exists; overwrite requires confirmation.",
                    payload={"code": "overwrite_needs_token", "path": _describe(target)["path"],
                             "warning": "Existing content will be replaced."},
                    arguments=arguments, correlation_id=correlation_id,
                    confirmation_token=token, applied=False,
                )
        if policy_dry_run():
            return respond(tool=tool, action="write_text", status="dry_run",
                           summary=f"[dry run] would write {len(content)} characters to "
                                   f"{target.name}.",
                           payload={"path": _describe(target)["path"],
                                    "characters": len(content)},
                           arguments=arguments, correlation_id=correlation_id, applied=False)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return respond(tool=tool, action="write_text", status="error",
                           summary=f"Failed to write file: {exc}",
                           payload={"code": "write_failed"},
                           arguments=arguments, correlation_id=correlation_id, applied=False)
        return respond(tool=tool, action="write_text", status="success",
                       summary=f"Wrote {target.name} ({len(content)} characters).",
                       payload={"path": _describe(target)["path"],
                                "bytes": len(content.encode('utf-8'))},
                       arguments=arguments, correlation_id=correlation_id, applied=True)

    return respond(tool=tool, action="workspace_fs", status="error",
                   summary="Unsupported workspace action.",
                   payload={"code": "invalid_action",
                            "allowed": ["list", "read_text", "search", "stat", "tree",
                                        "write_text"]},
                   arguments=arguments, correlation_id=correlation_id)


def policy_dry_run() -> bool:
    from mcp_server import policy
    return policy.dry_run_enabled()
