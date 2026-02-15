"""SEAL lesson persistence for YOPJ.

Stores and retrieves structured lessons in SEAL v1.0 format.
Each lesson is a JSON file; an index.json provides fast lookup by topic/category/tag.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


SEAL_SCHEMA_VERSION = "1.0"

# Controlled vocabulary for categories (SEAL v1.0)
VALID_CATEGORIES = {
    "technical_insight", "system_stability", "process_improvement",
    "architecture_decision", "debugging_pattern", "performance_finding",
    "security_finding", "user_preference",
}

# Valid evidence types (SEAL v1.0)
VALID_EVIDENCE_TYPES = {
    "file_reference", "metric", "observation", "external_source",
    "log_entry", "calibration_data",
}


def load_index(lessons_dir: str) -> dict:
    """Load the lesson index from a directory.

    Returns a dict with keys: lessons (list), by_topic, by_category, by_tag.
    Creates an empty index if none exists.
    """
    index_path = os.path.join(lessons_dir, "index.json")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "last_lesson_number": 0,
        "schema_version": SEAL_SCHEMA_VERSION,
        "lessons": [],
        "by_topic": {},
        "by_category": {},
        "by_tag": {},
    }


def save_index(lessons_dir: str, index: dict) -> None:
    """Save the lesson index to disk."""
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    index_path = os.path.join(lessons_dir, "index.json")
    os.makedirs(lessons_dir, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def load_lesson(lessons_dir: str, lesson_id: str) -> dict | None:
    """Load a single lesson by ID. Returns None if not found."""
    path = os.path.join(lessons_dir, f"{lesson_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_lesson(lessons_dir: str, lesson: dict) -> str:
    """Save a lesson to disk and update the index. Returns the lesson_id."""
    os.makedirs(lessons_dir, exist_ok=True)
    lesson_id = lesson["lesson_id"]
    path = os.path.join(lessons_dir, f"{lesson_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lesson, f, indent=2)

    # Update index
    index = load_index(lessons_dir)
    _update_index(index, lesson)
    save_index(lessons_dir, index)

    return lesson_id


def create_lesson(
    lessons_dir: str,
    prefix: str,
    topic: str,
    summary: str,
    category: str,
    insight: str,
    confidence: float,
    evidence: list[dict],
    tags: list[str] = None,
    decision_point: dict = None,
    scope: dict = None,
) -> dict:
    """Create a new SEAL v1.0 lesson.

    Args:
        lessons_dir: Directory to store lessons.
        prefix: Lesson ID prefix (e.g., "MARVIN").
        topic: Lesson topic.
        summary: Max 15-word summary.
        category: From VALID_CATEGORIES.
        insight: Key insight (min 20 chars).
        confidence: Float 0.0-1.0.
        evidence: List of evidence dicts (type, source, detail, timestamp).
        tags: Optional list of tags.
        decision_point: Optional decision point dict.
        scope: Optional scope dict with applies_when, does_not_apply_when.

    Returns:
        The complete lesson dict.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")

    # Determine next lesson number
    index = load_index(lessons_dir)
    num = index.get("last_lesson_number", 0) + 1
    lesson_id = f"{prefix}_{date_str}_{num:03d}"

    lesson = {
        "schema_version": SEAL_SCHEMA_VERSION,
        "lesson_id": lesson_id,
        "topic": topic,
        "summary": summary,
        "category": category,
        "confidence": confidence,
        "status": "active",
        "created": now.isoformat(),
        "last_validated": now.isoformat(),
        "content": {
            "insight": insight,
            "decision_point": decision_point or {},
            "evidence": evidence,
        },
        "meta": {
            "tags": tags or [],
            "scope": scope or {"applies_when": "", "does_not_apply_when": ""},
        },
    }

    # Save lesson file, then update index with correct lesson_number
    os.makedirs(lessons_dir, exist_ok=True)
    path = os.path.join(lessons_dir, f"{lesson_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lesson, f, indent=2)

    index["last_lesson_number"] = num
    _update_index(index, lesson)
    save_index(lessons_dir, index)
    return lesson


def query_by_category(lessons_dir: str, category: str) -> list[dict]:
    """Return all lessons in a given category."""
    index = load_index(lessons_dir)
    ids = index.get("by_category", {}).get(category, [])
    return [load_lesson(lessons_dir, lid) for lid in ids if load_lesson(lessons_dir, lid)]


def query_by_tag(lessons_dir: str, tag: str) -> list[dict]:
    """Return all lessons with a given tag."""
    index = load_index(lessons_dir)
    ids = index.get("by_tag", {}).get(tag, [])
    return [load_lesson(lessons_dir, lid) for lid in ids if load_lesson(lessons_dir, lid)]


def query_by_topic_keyword(lessons_dir: str, keyword: str) -> list[dict]:
    """Return lessons whose topic contains the keyword (case-insensitive)."""
    index = load_index(lessons_dir)
    keyword_lower = keyword.lower()
    matches = []
    for entry in index.get("lessons", []):
        if keyword_lower in entry.get("topic", "").lower():
            lesson = load_lesson(lessons_dir, entry["lesson_id"])
            if lesson:
                matches.append(lesson)
    return matches


def load_lessons_for_prompt(lessons_dir: str, max_lessons: int = 10, min_confidence: float = 0.4) -> str:
    """Load active SEAL lessons and format them for system prompt injection.

    Returns a compact text block of lessons, sorted by confidence (highest first).
    Each lesson is one line: "- [topic]: insight (confidence: N%)"

    Args:
        lessons_dir: Directory containing SEAL lessons.
        max_lessons: Maximum lessons to include.
        min_confidence: Minimum confidence to include a lesson.
    """
    index = load_index(lessons_dir)
    entries = index.get("lessons", [])

    # Filter active lessons above confidence threshold
    candidates = [
        e for e in entries
        if e.get("status") == "active" and e.get("confidence", 0) >= min_confidence
    ]

    # Sort by confidence descending
    candidates.sort(key=lambda e: e.get("confidence", 0), reverse=True)

    # Load and format top N
    lines = []
    for entry in candidates[:max_lessons]:
        lesson = load_lesson(lessons_dir, entry["lesson_id"])
        if not lesson:
            continue
        topic = lesson.get("topic", "unknown")
        insight = lesson.get("content", {}).get("insight", lesson.get("summary", ""))
        # Truncate long insights
        if len(insight) > 150:
            insight = insight[:147] + "..."
        conf = int(lesson.get("confidence", 0) * 100)
        lines.append(f"- [{topic}]: {insight} ({conf}%)")

    if not lines:
        return ""

    return "# Lessons from previous sessions\n" + "\n".join(lines)


def validate_lesson(lesson: dict) -> list[str]:
    """Validate a lesson against SEAL v1.0 requirements.

    Returns a list of error strings. Empty list means valid.
    """
    errors = []

    # Required fields
    for field in ("lesson_id", "topic", "summary", "category", "confidence", "content"):
        if field not in lesson:
            errors.append(f"Missing required field: {field}")

    # Category validation
    cat = lesson.get("category", "")
    if cat and cat not in VALID_CATEGORIES:
        errors.append(f"Invalid category: {cat}. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}")

    # Confidence range
    conf = lesson.get("confidence", 0)
    if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
        errors.append(f"Confidence must be 0.0-1.0, got: {conf}")

    # Summary length
    summary = lesson.get("summary", "")
    if len(summary.split()) > 20:
        errors.append(f"Summary too long ({len(summary.split())} words, max 20)")

    # Content validation
    content = lesson.get("content", {})
    if isinstance(content, dict):
        insight = content.get("insight", "")
        if len(insight) < 20:
            errors.append(f"Insight too short ({len(insight)} chars, min 20)")

        evidence = content.get("evidence", [])
        if not evidence:
            errors.append("At least one evidence item required")
        else:
            for i, ev in enumerate(evidence):
                ev_type = ev.get("type", "")
                if ev_type and ev_type not in VALID_EVIDENCE_TYPES:
                    errors.append(f"Evidence[{i}] invalid type: {ev_type}")

    return errors


def apply_confidence_decay(lessons_dir: str, decay_days: int = 30, decay_rate: float = 0.05,
                           min_confidence: float = 0.1) -> list[dict]:
    """Apply time-based confidence decay to lessons that haven't been revalidated.

    Lessons not validated within decay_days lose decay_rate per period.
    Lessons below min_confidence are marked 'deprecated'.

    Args:
        lessons_dir: Directory containing SEAL lessons.
        decay_days: Days before confidence starts decaying.
        decay_rate: Confidence reduction per decay period.
        min_confidence: Lessons below this threshold are deprecated.

    Returns:
        List of lessons that were modified (decayed or deprecated).
    """
    index = load_index(lessons_dir)
    now = datetime.now(timezone.utc)
    modified = []

    for entry in index.get("lessons", []):
        if entry.get("status") != "active":
            continue

        lesson = load_lesson(lessons_dir, entry["lesson_id"])
        if not lesson:
            continue

        last_validated = lesson.get("last_validated", lesson.get("created", ""))
        try:
            validated_dt = datetime.fromisoformat(last_validated)
        except (ValueError, TypeError):
            continue

        days_since = (now - validated_dt).days
        if days_since <= decay_days:
            continue

        # Calculate decay: one step per decay_days period since last validation
        periods = days_since // decay_days
        original_conf = lesson.get("confidence", 0.5)
        new_conf = max(0.0, original_conf - (periods * decay_rate))

        if new_conf < min_confidence:
            lesson["status"] = "deprecated"
            entry["status"] = "deprecated"

        lesson["confidence"] = round(new_conf, 3)
        entry["confidence"] = lesson["confidence"]

        # Save modified lesson
        path = os.path.join(lessons_dir, f"{lesson['lesson_id']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(lesson, f, indent=2)

        modified.append(lesson)

    if modified:
        save_index(lessons_dir, index)

    return modified


def revalidate_lesson(lessons_dir: str, lesson_id: str, new_confidence: float = None) -> dict | None:
    """Mark a lesson as revalidated (resets decay timer).

    Args:
        lessons_dir: Directory containing SEAL lessons.
        lesson_id: ID of the lesson to revalidate.
        new_confidence: Optional new confidence value. If None, keeps current.

    Returns:
        Updated lesson dict, or None if not found.
    """
    lesson = load_lesson(lessons_dir, lesson_id)
    if not lesson:
        return None

    now = datetime.now(timezone.utc).isoformat()
    lesson["last_validated"] = now
    lesson["status"] = "active"

    if new_confidence is not None:
        lesson["confidence"] = max(0.0, min(1.0, new_confidence))

    # Save lesson
    path = os.path.join(lessons_dir, f"{lesson_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lesson, f, indent=2)

    # Update index entry
    index = load_index(lessons_dir)
    for entry in index.get("lessons", []):
        if entry["lesson_id"] == lesson_id:
            entry["last_validated"] = now
            entry["status"] = "active"
            if new_confidence is not None:
                entry["confidence"] = lesson["confidence"]
            break
    save_index(lessons_dir, index)

    return lesson


def detect_conflicts(lessons_dir: str) -> list[dict]:
    """Find lessons on the same topic that may contradict each other.

    Returns a list of conflict records with {topic, lessons, reason}.
    """
    index = load_index(lessons_dir)
    conflicts = []

    # Group active lessons by topic
    by_topic = index.get("by_topic", {})
    for topic, lesson_ids in by_topic.items():
        if len(lesson_ids) < 2:
            continue

        # Load all active lessons for this topic
        active = []
        for lid in lesson_ids:
            lesson = load_lesson(lessons_dir, lid)
            if lesson and lesson.get("status") == "active":
                active.append(lesson)

        if len(active) < 2:
            continue

        # Check for contradictions: same topic, different insights
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                a_insight = active[i].get("content", {}).get("insight", "")
                b_insight = active[j].get("content", {}).get("insight", "")

                # Simple heuristic: if both insights are substantial and different
                if (len(a_insight) > 30 and len(b_insight) > 30
                        and a_insight.lower() != b_insight.lower()):
                    conflicts.append({
                        "topic": topic,
                        "lessons": [active[i]["lesson_id"], active[j]["lesson_id"]],
                        "reason": "Multiple active lessons on same topic with different insights",
                    })

    return conflicts


def _update_index(index: dict, lesson: dict) -> None:
    """Update index entries for a lesson."""
    lid = lesson["lesson_id"]
    topic = lesson.get("topic", "")
    category = lesson.get("category", "")
    tags = lesson.get("meta", {}).get("tags", [])

    # Update lessons list
    existing_ids = {e["lesson_id"] for e in index.get("lessons", [])}
    if lid not in existing_ids:
        index.setdefault("lessons", []).append({
            "lesson_id": lid,
            "topic": topic,
            "summary": lesson.get("summary", ""),
            "category": category,
            "confidence": lesson.get("confidence", 0.0),
            "status": lesson.get("status", "active"),
            "created": lesson.get("created", ""),
            "last_validated": lesson.get("last_validated", ""),
        })

    # Update by_topic
    index.setdefault("by_topic", {}).setdefault(topic, [])
    if lid not in index["by_topic"][topic]:
        index["by_topic"][topic].append(lid)

    # Update by_category
    if category:
        index.setdefault("by_category", {}).setdefault(category, [])
        if lid not in index["by_category"][category]:
            index["by_category"][category].append(lid)

    # Update by_tag
    for tag in tags:
        index.setdefault("by_tag", {}).setdefault(tag, [])
        if lid not in index["by_tag"][tag]:
            index["by_tag"][tag].append(lid)
