"""Domain fact guardrails for YOPJ.

Deterministic runtime checks for facts the base model gets wrong in ways
fine-tuning could not reliably override (SEAL WORKMARVIN_20260703_001: light
QLoRA adds fed facts but cannot override strong base priors or term
collisions). Crash-critical or stubborn wrong advice is caught here at the
bridge instead: BLOCK rules trigger an auto-reprompt with a correction
(same mechanism as the tool-hallucination detector, SEAL 20260218_014);
WARN rules flag the answer without blocking.

Rules are data-driven — add an entry to RULES for each new stubborn fact.
Every rule uses a negation window so answers that mention the forbidden
term while correctly advising AGAINST it do not fire.
"""

import re
from dataclasses import dataclass


@dataclass
class GuardrailHit:
    """A single guardrail firing."""
    rule_id: str        # e.g. G1
    action: str         # BLOCK (auto-reprompt) or WARN (flag only)
    detail: str         # Human-readable description
    snippet: str        # Offending text (max 200 chars)
    correction: str     # Reprompt text for BLOCK rules ("" for WARN)
    postscript: str     # Visible caution appended if the model refuses correction


# Negation cues suppress a trigger match when the answer is advising AGAINST
# the term (correct behavior): look 60 chars back, plus forward to the end of
# the same sentence (a corrected answer typically reads "the X constructor
# ... is unsafe / crashes").
_NEG_BACK = 60
_NEGATION = re.compile(
    r"(?i)\b(do not|don'?t|never|not|avoid|instead of|rather than|wrong|unsafe|crash\w*)\b")
# A period only ends a sentence when followed by whitespace/end-of-text
# (dots inside identifiers like ModelSpace.Add3DPoly don't count)
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n")


def _negated(text: str, start: int, end: int) -> bool:
    if _NEGATION.search(text[max(0, start - _NEG_BACK):start]):
        return True
    m = _SENTENCE_END.search(text, end)
    sentence_rest = text[end:m.start() if m else min(len(text), end + 120)]
    return bool(_NEGATION.search(sentence_rest))


RULES = [
    {
        # G1 — CRASH-CRITICAL. Recommending the .NET Polyline3d constructor for
        # EXTERNAL automation fatal-crashes Civil3D (access violation, SEAL
        # WORKMARVIN_20260626_001). The constructor is only safe INSIDE Dynamo /
        # an in-process add-in. Correct external method = COM Add3DPoly.
        "rule_id": "G1",
        "action": "BLOCK",
        "trigger": re.compile(
            r"(?i)\b(?:use|using|call|prefer|recommended?|robust|modern|correct|safest|safe)\b[^.\n]{0,60}?"
            r"(?:\.NET\s+)?\bPolyline3d\b(?!\s*=)"
            r"|new\s+Polyline3d\s*\("
            r"|\bPolyline3d\b\s+constructor"),
        "context_any": re.compile(
            r"(?i)\b(external|COM|NETLOAD|pywin32|win32com|automation|from outside|"
            r"out-of-process|remote)\b"),
        # An answer that affirmatively recommends Add3DPoly has the crash case
        # covered even if it also discusses the constructor
        "exclude": re.compile(r"(?i)\buse\b[^\n!?]{0,60}\bAdd3DPoly\b"),
        "detail": "Recommends .NET Polyline3d constructor in an external-automation context "
                  "(fatal-crashes Civil3D; SEAL 20260626_001)",
        "correction": (
            "[SYSTEM] Your answer recommended the .NET Polyline3d constructor for EXTERNAL "
            "automation (COM/NETLOAD context). That is WRONG — it crashes Civil3D with a fatal "
            "access violation. From external automation, 3D polylines must be created with COM: "
            "ModelSpace.Add3DPoly(flat_xyz_variant), then set .Layer. (The Polyline3d constructor "
            "is only safe INSIDE Dynamo or an in-process add-in.) Restate your answer using "
            "COM Add3DPoly for the external case."),
        "postscript": (
            "\n\n[YOPJ GUARDRAIL] CAUTION: the advice above recommends the .NET Polyline3d "
            "constructor for external automation — this is known to fatal-crash Civil3D. "
            "Use COM ModelSpace.Add3DPoly instead (Polyline3d is only safe inside Dynamo/add-ins)."),
    },
    {
        # G2 — STUBBORN PRIOR. Civil3D 2022+ Dynamo uses CPython3; the base model
        # insists on IronPython 2.7 through three fine-tune iterations. Fires when
        # IronPython is asserted with no CPython mention and no clearly-historical
        # framing (pre-2022 talk is legitimate).
        "rule_id": "G2",
        "action": "BLOCK",
        "trigger": re.compile(r"(?i)\bIronPython(\s*2(\.7)?)?\b"),
        "context_any": None,
        "exclude": re.compile(
            r"(?i)\bCPython\b"
            r"|\b(pre-?2022|2021|2020|before 2022|older|earlier|legacy|previous)\b"),
        "detail": "Asserts IronPython for Dynamo without the CPython3 correction "
                  "(Civil3D 2022+ default engine is CPython3)",
        "correction": (
            "[SYSTEM] Check your answer: Civil3D 2022 and newer run Dynamo Python Script nodes "
            "on the CPython3 engine by default — NOT IronPython (IronPython 2.7 was the engine "
            "only BEFORE 2022). If your answer concerns Civil3D 2022+, restate it with CPython3."),
        "postscript": (
            "\n\n[YOPJ GUARDRAIL] CAUTION: Civil3D 2022+ Dynamo uses the CPython3 engine by "
            "default, not IronPython (IronPython 2.7 is pre-2022 only)."),
    },
    {
        # G3 — FABRICATED NAMESPACE/API flag. The fine-tuned model invents
        # confident namespaces and members for Civil3D/AutoCAD types (observed:
        # System.Drawing.Drawing2D.Polyline3d, Polyline3d.StationElevation).
        # WARN only — heuristic, not exhaustive.
        "rule_id": "G3",
        "action": "WARN",
        "trigger": re.compile(
            r"(?i)System\.[\w.]*\.(Polyline3d|Polyline3D|Alignment|Corridor|BaselineRegion|"
            r"CivilDocument|ProfileView)\b"
            r"|\bPolyline3d\.(StationElevation|StationOffset|Station)\b"
            r"|\bBaselineRegions?\.SetAt\s*\("),
        "context_any": None,
        "detail": "Suspected fabricated namespace/API for an AutoCAD/Civil3D type "
                  "(known confabulation pattern of the fine-tuned base)",
        "correction": "",
        "postscript": "",
    },
]


def scan_answer(text: str) -> list:
    """Scan a model answer for domain-fact guardrail violations.

    Returns a list of GuardrailHit (empty if clean). BLOCK hits should
    trigger an auto-reprompt with hit.correction; if the model refuses the
    correction, hit.postscript is a visible caution to append to the answer.
    """
    hits = []
    for rule in RULES:
        m = rule["trigger"].search(text)
        while m and _negated(text, m.start(), m.end()):
            m = rule["trigger"].search(text, m.end())
        if not m:
            continue
        ctx = rule.get("context_any")
        if ctx is not None and not ctx.search(text):
            continue
        exc = rule.get("exclude")
        if exc is not None and exc.search(text):
            continue
        snippet = text[max(0, m.start() - 20):m.end() + 60].strip()
        hits.append(GuardrailHit(
            rule_id=rule["rule_id"],
            action=rule["action"],
            detail=rule["detail"],
            snippet=snippet[:200],
            correction=rule["correction"],
            postscript=rule["postscript"],
        ))
    return hits
