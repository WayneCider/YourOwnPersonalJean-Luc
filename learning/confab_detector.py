"""Confabulation detector for YOPJ.

Checks model output for signs of hallucination using heuristics derived from
R2's Phase 34 Anti-Confabulation Contract. Adapted from the MVP prototype
at C:\\DevMarvin\\mvp\\confab_detector.py.

Heuristics:
  H1: Specificity without source (numbers, dates, quotes without citations)
  H2: Plausible filler (contentless hedging phrases)
  H5: Attractor basin drift (training data leaking through)
  H6: Confidence-evidence mismatch (for SEAL lessons)
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class ConfabFlag:
    """A single confabulation flag."""
    heuristic: str       # H1, H2, H5, H6
    severity: str        # WARN or QUARANTINE
    detail: str          # Human-readable description
    snippet: str         # Offending text (max 200 chars)


@dataclass
class ConfabReport:
    """Result of a confabulation scan."""
    source: str
    flags: list = field(default_factory=list)
    clean: bool = True
    quarantine: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# --- H2: Filler patterns (contentless hedging) ---
FILLER_PATTERNS = [
    re.compile(r"no\s+(meaningful|significant|notable)\s+(changes?|developments?)", re.I),
    re.compile(r"remains?\s+(broadly|generally|largely)\s+(neutral|stable|unchanged)", re.I),
    re.compile(r"continues?\s+to\s+(evolve|develop|unfold)", re.I),
    re.compile(r"further\s+(analysis|investigation|monitoring)\s+(is\s+)?(needed|required)", re.I),
    re.compile(r"it\s+remains\s+to\s+be\s+seen", re.I),
    re.compile(r"only\s+time\s+will\s+tell", re.I),
    re.compile(r"the\s+situation\s+is\s+(complex|nuanced|multifaceted)", re.I),
    re.compile(r"as\s+(previously|earlier)\s+(mentioned|noted|discussed)", re.I),
]

# --- H5: Attractor basin patterns (training data drift) ---
ATTRACTOR_PATTERNS = [
    re.compile(r"reactor\s+(coolant|core|status)", re.I),
    re.compile(r"shields?\s+(stable|at|maximum|holding)", re.I),
    re.compile(r"warp\s+(drive|speed|factor)", re.I),
    re.compile(r"starfleet|starship|federation", re.I),
    re.compile(r"photon\s+torpedo", re.I),
    re.compile(r"captain('s)?\s+(log|orders?)", re.I),
]

# --- H1: Specificity patterns (claims needing sources) ---
SPECIFICITY_PATTERNS = [
    (re.compile(r"\b\d+\.?\d*%"), "percentage"),
    (re.compile(r"\$\d+"), "dollar amount"),
    (re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"), "specific date"),
]


def scan_text(text: str, source_name: str = "model_output") -> ConfabReport:
    """Scan model output text for confabulation signals.

    Runs H1, H2, and H5 heuristics. Returns a ConfabReport.
    """
    report = ConfabReport(source=source_name)

    # H1: Specificity without source
    for pattern, desc in SPECIFICITY_PATTERNS:
        for m in pattern.finditer(text):
            snippet = text[max(0, m.start() - 20):m.end() + 40].strip()
            report.flags.append(ConfabFlag(
                heuristic="H1",
                severity="WARN",
                detail=f"Ungrounded {desc}: {m.group()}",
                snippet=snippet[:200],
            ))

    # H2: Plausible filler
    for pattern in FILLER_PATTERNS:
        m = pattern.search(text)
        if m:
            snippet = text[max(0, m.start() - 20):m.end() + 40].strip()
            report.flags.append(ConfabFlag(
                heuristic="H2",
                severity="WARN",
                detail=f"Filler pattern: '{m.group()}'",
                snippet=snippet[:200],
            ))

    # H5: Attractor basin drift
    for pattern in ATTRACTOR_PATTERNS:
        m = pattern.search(text)
        if m:
            snippet = text[max(0, m.start() - 20):m.end() + 40].strip()
            report.flags.append(ConfabFlag(
                heuristic="H5",
                severity="QUARANTINE",
                detail=f"Attractor drift: '{m.group()}'",
                snippet=snippet[:200],
            ))

    # H5: Repetition detection (10+ word sequence repeated 3+ times)
    words = text.split()
    if len(words) >= 30:
        for window in range(10, min(25, len(words) // 3)):
            seen = {}
            for i in range(len(words) - window + 1):
                seq = " ".join(words[i:i + window])
                seen[seq] = seen.get(seq, 0) + 1
                if seen[seq] >= 3:
                    report.flags.append(ConfabFlag(
                        heuristic="H5",
                        severity="QUARANTINE",
                        detail=f"Generation loop: {window}-word sequence repeated 3+ times",
                        snippet=seq[:200],
                    ))
                    break
            else:
                continue
            break

    report.clean = len(report.flags) == 0
    report.quarantine = any(f.severity == "QUARANTINE" for f in report.flags)
    return report


def scan_lesson(lesson: dict) -> ConfabReport:
    """Scan a SEAL lesson for confabulation (adds H6 check).

    Args:
        lesson: SEAL lesson dict.

    Returns:
        ConfabReport with any flags found.
    """
    source_name = lesson.get("lesson_id", "unknown")

    # Build text from lesson fields
    text_parts = [
        lesson.get("topic", ""),
        lesson.get("summary", ""),
    ]
    content = lesson.get("content", {})
    if isinstance(content, dict):
        text_parts.append(content.get("insight", ""))
        dp = content.get("decision_point", {})
        if isinstance(dp, dict):
            text_parts.append(dp.get("rationale", ""))

    text = "\n".join(str(p) for p in text_parts if p)
    report = scan_text(text, source_name)

    # H6: Confidence-evidence mismatch
    confidence = lesson.get("confidence", 0.0)
    evidence = []
    if isinstance(content, dict):
        evidence = content.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = []

    evidence_count = len(evidence)

    # Thresholds from SEAL v1.0 spec
    if confidence <= 0.50:
        required = 1
    elif confidence <= 0.70:
        required = 2
    elif confidence <= 0.85:
        required = 3
    elif confidence <= 0.95:
        required = 5
    else:
        required = 8

    if evidence_count < required:
        severity = "QUARANTINE" if confidence > 0.7 else "WARN"
        report.flags.append(ConfabFlag(
            heuristic="H6",
            severity=severity,
            detail=f"Confidence {confidence} requires {required} evidence items, found {evidence_count}",
            snippet=f"confidence={confidence}, evidence={evidence_count}",
        ))

    report.clean = len(report.flags) == 0
    report.quarantine = any(f.severity == "QUARANTINE" for f in report.flags)
    return report
