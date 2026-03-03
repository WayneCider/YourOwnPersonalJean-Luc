"""Task scheduling tool for YOPJ.

Persistent task list stored as JSON on disk. Tasks live in the current
working directory as `.yopj_tasks.json`. Supports add, list, complete,
and delete operations with optional due dates.

No external dependencies (stdlib only).
"""

import json
import os
from datetime import datetime
from pathlib import Path

TASKS_FILENAME = ".yopj_tasks.json"


def _tasks_path(cwd: str = ".") -> Path:
    """Resolve the tasks file path relative to cwd."""
    return Path(cwd).resolve() / TASKS_FILENAME


def _load_tasks(cwd: str = ".") -> list:
    """Load tasks from disk. Returns empty list if file doesn't exist."""
    path = _tasks_path(cwd)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_tasks(tasks: list, cwd: str = ".") -> None:
    """Write tasks list to disk."""
    path = _tasks_path(cwd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)


def _next_id(tasks: list) -> int:
    """Get the next available task ID."""
    if not tasks:
        return 1
    return max(t.get("id", 0) for t in tasks) + 1


def _now_iso() -> str:
    """Current timestamp in ISO 8601 format."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def task_schedule(action: str, subject: str = "", task_id: int = 0,
                  description: str = "", due: str = "",
                  status_filter: str = "", cwd: str = ".") -> dict:
    """Manage a persistent task list.

    Args:
        action: One of "add", "list", "complete", "delete".
        subject: Task title (required for "add").
        task_id: Task ID (required for "complete" and "delete").
        description: Optional details for "add".
        due: Optional due date for "add" (any format, stored as-is).
        status_filter: For "list" — filter by "pending", "completed", or "" for all.
        cwd: Working directory where .yopj_tasks.json lives.

    Returns:
        dict with ok, result data or error.
    """
    action = action.strip().lower()
    if action not in ("add", "list", "complete", "delete"):
        return {"ok": False, "error": f"Unknown action '{action}'. Use: add, list, complete, delete"}

    tasks = _load_tasks(cwd)

    # --- ADD ---
    if action == "add":
        if not subject.strip():
            return {"ok": False, "error": "subject is required for 'add'"}
        task = {
            "id": _next_id(tasks),
            "subject": subject.strip(),
            "description": description.strip(),
            "status": "pending",
            "created": _now_iso(),
            "due": due.strip(),
            "completed_at": "",
        }
        tasks.append(task)
        _save_tasks(tasks, cwd)
        return {"ok": True, "action": "add", "task": task}

    # --- LIST ---
    if action == "list":
        filtered = tasks
        if status_filter.strip().lower() in ("pending", "completed"):
            filtered = [t for t in tasks if t.get("status") == status_filter.strip().lower()]
        summary = []
        for t in filtered:
            entry = f"[{t['id']}] {t['subject']}"
            if t.get("status") == "completed":
                entry += " (DONE)"
            if t.get("due"):
                entry += f" — due: {t['due']}"
            summary.append(entry)
        return {
            "ok": True,
            "action": "list",
            "count": len(filtered),
            "tasks": filtered,
            "summary": "\n".join(summary) if summary else "(no tasks)",
        }

    # --- COMPLETE ---
    if action == "complete":
        if task_id <= 0:
            return {"ok": False, "error": "task_id is required for 'complete'"}
        for t in tasks:
            if t.get("id") == task_id:
                if t.get("status") == "completed":
                    return {"ok": True, "action": "complete", "note": f"Task {task_id} was already completed"}
                t["status"] = "completed"
                t["completed_at"] = _now_iso()
                _save_tasks(tasks, cwd)
                return {"ok": True, "action": "complete", "task": t}
        return {"ok": False, "error": f"Task {task_id} not found"}

    # --- DELETE ---
    if action == "delete":
        if task_id <= 0:
            return {"ok": False, "error": "task_id is required for 'delete'"}
        for i, t in enumerate(tasks):
            if t.get("id") == task_id:
                removed = tasks.pop(i)
                _save_tasks(tasks, cwd)
                return {"ok": True, "action": "delete", "removed": removed}
        return {"ok": False, "error": f"Task {task_id} not found"}

    return {"ok": False, "error": "Unreachable"}


def register_tools(registry):
    """Register task_schedule as an optional YOPJ tool."""
    registry.register_tool(
        "task_schedule",
        task_schedule,
        "Manage a persistent task list (add, list, complete, delete tasks with optional due dates)"
    )
