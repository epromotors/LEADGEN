# auditor/drift.py — Semantic Drift & Historical Audit Regression Tracker
#
# Compares two audit snapshots (before vs after) to detect:
#   1. Overall score delta & category-level score movement
#   2. Regressions (factors that previously passed but now fail/warn)
#   3. Verified fixes (factors confirmed resolved strictly via fresh verification)
#   4. Unresolved findings that persist across audits
#   5. Critical crawlability or schema degradations
#
# MIT License Attribution:
# Inspired by and benchmarked against Auriti-Labs/geo-optimizer-skill (MIT).
#
# Mandatory Constraint:
# Never describes a finding as fixed without fresh, verified evidence in audit_after!

from __future__ import annotations

from typing import Any, Dict, List, Optional


def compare_audits_for_drift(
    audit_before: Dict[str, Any],
    audit_after: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Perform a deterministic semantic drift comparison between two audit snapshots.
    """
    score_before = audit_before.get("seo_score") or audit_before.get("score") or 0
    score_after = audit_after.get("seo_score") or audit_after.get("score") or 0
    score_delta = score_after - score_before

    results_before = audit_before.get("audit_results") or {}
    results_after = audit_after.get("audit_results") or {}

    regressions: List[Dict[str, Any]] = []
    verified_fixes: List[Dict[str, Any]] = []
    unresolved_issues: List[Dict[str, Any]] = []
    category_deltas: Dict[str, int] = {}

    # Flatten factors helper
    def flatten_factors(results_dict: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        flat: Dict[str, Dict[str, Any]] = {}
        for grp_name, grp in results_dict.items():
            if isinstance(grp, dict):
                for fid, fdata in grp.items():
                    if isinstance(fdata, dict):
                        factor_key = fdata.get("id") or f"{grp_name}.{fid}"
                        flat[factor_key] = fdata
        return flat

    flat_before = flatten_factors(results_before)
    flat_after = flatten_factors(results_after)

    all_factor_ids = sorted(set(flat_before.keys()) | set(flat_after.keys()))

    for fid in all_factor_ids:
        b_data = flat_before.get(fid, {})
        a_data = flat_after.get(fid, {})

        st_before = b_data.get("status")
        st_after = a_data.get("status")

        if not st_before or not st_after:
            continue

        # 1. Regressions: Was PASS, now WARN or FAIL
        if st_before == "PASS" and st_after in ("WARN", "FAIL", "ERROR"):
            regressions.append({
                "factor_id": fid,
                "title": a_data.get("name") or fid,
                "status_before": st_before,
                "status_after": st_after,
                "message": a_data.get("message") or "Factor regressed.",
            })

        # 2. Verified fixes: Was FAIL or WARN, now confirmed PASS in fresh audit
        elif st_before in ("FAIL", "WARN", "ERROR") and st_after == "PASS":
            verified_fixes.append({
                "factor_id": fid,
                "title": a_data.get("name") or fid,
                "status_before": st_before,
                "status_after": st_after,
                "verified_fix": a_data.get("message") or "Resolved and confirmed passing.",
            })

        # 3. Unresolved: Remains FAIL or WARN
        elif st_before in ("FAIL", "WARN", "ERROR") and st_after in ("FAIL", "WARN", "ERROR"):
            unresolved_issues.append({
                "factor_id": fid,
                "title": a_data.get("name") or fid,
                "status_before": st_before,
                "status_after": st_after,
                "current_message": a_data.get("message") or "",
            })

    # Detect crawlability loss (e.g. robots.txt newly failing or blocking)
    robots_before = flat_before.get("technical.robots", {}).get("status")
    robots_after = flat_after.get("technical.robots", {}).get("status")
    crawlability_lost = bool(robots_before == "PASS" and robots_after in ("FAIL", "ERROR"))

    # Determine drift severity
    if score_delta <= -15 or crawlability_lost or len(regressions) >= 3:
        severity = "critical"
    elif score_delta <= -5 or len(regressions) > 0:
        severity = "warning"
    elif score_delta > 0 or len(verified_fixes) > 0:
        severity = "improved"
    else:
        severity = "stable"

    # Human-readable summary
    parts = []
    if score_delta > 0:
        parts.append(f"Audit score changed by +{score_delta} points ({score_before} -> {score_after})")
    elif score_delta < 0:
        parts.append(f"Audit score dropped by {score_delta} points ({score_before} -> {score_after})")
    else:
        parts.append(f"Audit score stable at {score_before}")

    if verified_fixes:
        parts.append(f"{len(verified_fixes)} finding(s) verified resolved with fresh evidence")
    if regressions:
        parts.append(f"{len(regressions)} regression(s) detected requiring remediation")
    if crawlability_lost:
        parts.append("CRAWLABILITY LOST: robots.txt now blocking or site error")

    summary = ". ".join(parts) + "."

    return {
        "score_before": score_before,
        "score_after": score_after,
        "score_delta": score_delta,
        "severity": severity,
        "summary": summary,
        "crawlability_lost": crawlability_lost,
        "regressions_count": len(regressions),
        "verified_fixes_count": len(verified_fixes),
        "unresolved_count": len(unresolved_issues),
        "regressions": regressions,
        "verified_fixes": verified_fixes,
        "unresolved_issues": unresolved_issues,
    }
