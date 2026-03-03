"""Calendar check tool for YOPJ.

Read-only view of upcoming deadlines and events. Pulls from two sources:
1. Tasks with due dates from .yopj_tasks.json (created by task_schedule)
2. Manual calendar entries from .yopj_calendar.json

No external dependencies (stdlib only). No API calls — fully local.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

TASKS_FILENAME = ".yopj_tasks.json"
CALENDAR_FILENAME = ".yopj_calendar.json"


def _resolve(filename: str, cwd: str = ".") -> Path:
    return Path(cwd).resolve() / filename


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _parse_date(s: str):
    """Try to parse a date string. Returns datetime.date or None."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def calendar_check(days_ahead: int = 7, include_completed: bool = False,
                   cwd: str = ".") -> dict:
    """Check upcoming deadlines and calendar events.

    Args:
        days_ahead: How many days ahead to look (default 7).
        include_completed: Whether to include completed tasks (default False).
        cwd: Working directory containing .yopj_tasks.json and .yopj_calendar.json.

    Returns:
        dict with ok, upcoming items grouped by date, overdue items, and summary.
    """
    today = datetime.now().date()
    horizon = today + timedelta(days=max(1, min(days_ahead, 365)))

    items = []

    # Source 1: Tasks with due dates
    tasks = _load_json(_resolve(TASKS_FILENAME, cwd))
    for t in tasks:
        if not t.get("due"):
            continue
        if not include_completed and t.get("status") == "completed":
            continue
        due = _parse_date(t["due"])
        if due is None:
            continue
        items.append({
            "date": due.isoformat(),
            "source": "task",
            "id": t.get("id"),
            "subject": t.get("subject", ""),
            "status": t.get("status", "pending"),
        })

    # Source 2: Calendar entries
    cal = _load_json(_resolve(CALENDAR_FILENAME, cwd))
    for entry in cal:
        if not entry.get("date"):
            continue
        d = _parse_date(entry["date"])
        if d is None:
            continue
        items.append({
            "date": d.isoformat(),
            "source": "calendar",
            "subject": entry.get("subject", entry.get("title", "")),
            "note": entry.get("note", entry.get("description", "")),
        })

    # Partition: overdue vs upcoming vs beyond horizon
    overdue = [i for i in items if _parse_date(i["date"]) and _parse_date(i["date"]) < today]
    upcoming = [i for i in items
                if _parse_date(i["date"]) and today <= _parse_date(i["date"]) <= horizon]
    upcoming.sort(key=lambda x: x["date"])
    overdue.sort(key=lambda x: x["date"])

    # Build summary
    lines = []
    if overdue:
        lines.append(f"OVERDUE ({len(overdue)}):")
        for i in overdue:
            lines.append(f"  {i['date']} — {i['subject']}")
    if upcoming:
        lines.append(f"UPCOMING (next {days_ahead} days, {len(upcoming)} items):")
        for i in upcoming:
            tag = f" [{i['source']}]" if i.get("source") == "calendar" else ""
            lines.append(f"  {i['date']} — {i['subject']}{tag}")
    if not overdue and not upcoming:
        lines.append(f"Nothing due in the next {days_ahead} days.")

    return {
        "ok": True,
        "today": today.isoformat(),
        "horizon": horizon.isoformat(),
        "overdue": overdue,
        "upcoming": upcoming,
        "summary": "\n".join(lines),
    }


def register_tools(registry):
    """Register calendar_check as an optional YOPJ tool."""
    registry.register_tool(
        "calendar_check",
        calendar_check,
        "Check upcoming deadlines and calendar events (reads tasks + calendar file)"
    )
