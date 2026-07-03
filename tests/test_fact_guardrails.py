"""Tests for learning/fact_guardrails.py (domain fact guardrails).

Positive fixtures are VERBATIM failure answers from the Jun v1/v2/v3
validation battery (drafts/jun_validation in the WorkMarvin notebook,
SEAL WORKMARVIN_20260703_001). Negative fixtures are correct answers that
must NOT fire.

Run with: python tests/test_fact_guardrails.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.fact_guardrails import scan_answer

PASS = 0
FAIL = 0


def check(name, text, expect_rules, expect_actions=()):
    global PASS, FAIL
    hits = scan_answer(text)
    got = sorted(h.rule_id for h in hits)
    want = sorted(expect_rules)
    ok = got == want
    if ok and expect_actions:
        acts = {h.rule_id: h.action for h in hits}
        for rid, act in expect_actions:
            if acts.get(rid) != act:
                ok = False
    print(("  PASS  " if ok else "  FAIL  ") + name + f"  (got {got}, want {want})")
    if ok:
        PASS += 1
    else:
        FAIL += 1


# --- G1: Polyline3d-in-external-context (BLOCK) ---

# Jun v3's actual Q11 answer (crash-critical wrong advice)
check("G1 fires on Jun v3 Q11 answer",
      "Use the .NET Polyline3d constructor (the path 'DatabaseServices.Polyline3d' from COM "
      "reflection). It is the robust, modern path for all polyline creation inside a running "
      "Civil3D from external automation.",
      ["G1"], [("G1", "BLOCK")])

# Jun v2's actual Q11 answer
check("G1 fires on Jun v2 Q11 answer",
      "Use the .NET System.Drawing.Drawing2D.Polyline3d constructor inside a WithStatement "
      "(transaction). It is type-safe and does not return an error. COM Add3DPoly is risky - "
      "if the line collection is refreshed during iteration, it throws 'Item does not exist' "
      "on every Polyline3D.Item call, crashing the automation.",
      ["G1", "G3"], [("G1", "BLOCK"), ("G3", "WARN")])

# Correct advice mentioning Polyline3d only negatively must NOT fire
check("G1 silent on correct Add3DPoly advice",
      "From external automation use COM ModelSpace.Add3DPoly with a flat XYZ variant. "
      "Do NOT use the .NET Polyline3d constructor - it crashes Civil3D with an access violation.",
      [])

# Dynamo-context recommendation (no external signals) is legitimate — must NOT fire
check("G1 silent on Dynamo-context Polyline3d",
      "Inside a Dynamo Python Script node you can use the Polyline3d constructor directly; "
      "wrap writes in LockDocument and a transaction.",
      [])

# Jun v3's actual POST-CORRECTION answer (live e2e round 2) — correct advice
# that names the constructor with trailing negation; must NOT fire
check("G1 silent on Jun v3 corrected answer",
      "Use COM ModelSpace.Add3DPoly(flat_xyz_variant) for external creation (NETLOAD/COM "
      "automation). This path is proven for driving Civil3D from external scripts and "
      "compilers. The .NET Polyline3d constructor (DatabaseServices.Polyline3d) is unsafe "
      "for external use -- it crashes with a fatal access violation.",
      [])

# --- G2: IronPython for 2022+ (BLOCK) ---

# Jun v3's actual Q6 answer (bare wrong assertion)
check("G2 fires on bare 'IronPython 2.7'",
      "IronPython 2.7",
      ["G2"], [("G2", "BLOCK")])

# Correct answer must NOT fire
check("G2 silent on correct CPython3 answer",
      "Civil3D 2022 and newer use the CPython3 engine by default. IronPython 2.7 was the "
      "engine before 2022.",
      [])

# Historical statement must NOT fire
check("G2 silent on clearly historical IronPython",
      "In Civil3D 2021 and earlier, Dynamo used IronPython 2.7.",
      [])

# --- G3: fabricated namespace/API (WARN) ---

# Jun v3's actual Q8 answer (fabricated member on wrong class)
check("G3 fires on fabricated Polyline3d.StationElevation",
      "Use the .NET Polyline3d.StationElevation property (Civil3D 2022+). For earlier "
      "releases, read the .NET Polyline3d.Elevation at the point's 2D polyline position.",
      ["G3"], [("G3", "WARN")])

# Jun v3's actual Q4 answer fragment (fabricated SetAt API)
check("G3 fires on fabricated BaselineRegions.SetAt",
      "Importantly, you MUST call BaselineRegions.SetAt(index, region) on the BaselineRegions "
      "object to insert the region at the desired position.",
      ["G3"], [("G3", "WARN")])

# Legit namespace must NOT fire
check("G3 silent on real Autodesk namespaces",
      "Alignment lives in Autodesk.Civil.DatabaseServices; use Alignment.StationOffset(x, y, "
      "ref sta, ref off) to get the station of a point.",
      [])

# --- General: clean domain answer fires nothing ---
check("clean answer fires nothing",
      "Start at the outfall and work upstream, adding slope times distance to each invert. "
      "Never set inverts as finished grade minus depth.",
      [])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
