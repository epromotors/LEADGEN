#!/usr/bin/env python3
"""Static consistency checks for LEADGEN's Phase 0 Agent Brain."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / ".agent"
ENGINE = ROOT / "backend/app/engines/audit_engine.py"
MODELS = ROOT / "backend/app/models.py"
SCHEMAS = ROOT / "backend/app/schemas.py"
CONFIG = ROOT / "auditor/auditor/config.py"
FRONTEND = ROOT / "frontend/src/pages/Audits.jsx"


def load_json(name: str) -> dict[str, Any]:
    path = AGENT / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def assignment_dict(path: Path, name: str) -> ast.Dict:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                if isinstance(node.value, ast.Dict):
                    return node.value
    raise ValueError(f"Could not find dictionary assignment {name!r} in {path}")


def executable_factors() -> dict[str, str]:
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"), filename=str(ENGINE))
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef) or func.name != "_run_audit_sync":
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "audit_results" for target in node.targets):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            factors: dict[str, str] = {}
            for axis_node, tests_node in zip(node.value.keys, node.value.values):
                axis = ast.literal_eval(axis_node)
                if not isinstance(tests_node, ast.Dict):
                    continue
                for key_node, call_node in zip(tests_node.keys, tests_node.values):
                    key = ast.literal_eval(key_node)
                    function = call_node.func.id if isinstance(call_node, ast.Call) and isinstance(call_node.func, ast.Name) else ast.unparse(call_node)
                    factors[f"{axis}.{key}"] = function
            return factors
    raise ValueError("Could not find audit_results in _run_audit_sync")


def class_fields(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                field.target.id
                for field in node.body
                if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)
            }
    raise ValueError(f"Could not find class {class_name!r} in {path}")


def module_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def frontend_keys() -> set[str]:
    text = FRONTEND.read_text(encoding="utf-8")
    if "structuredGroups(audit).map" in text:
        return {"__registry_driven__"}
    try:
        group_text = text.split("const AUDIT_GROUPS =", 1)[1].split("const RAW_CHECK_MAP =", 1)[0]
    except IndexError as exc:
        raise ValueError("Could not isolate AUDIT_GROUPS in Audits.jsx") from exc
    return set(re.findall(r"key:\s*'([^']+)'", group_text))


def report(strict: bool) -> int:
    required = ["brain.json", "rules.json", "architecture.json", "task_state.json", "factor_registry.json"]
    errors: list[str] = []
    warnings: list[str] = []
    for name in required:
        if not (AGENT / name).is_file():
            errors.append(f"Missing control-plane file: .agent/{name}")

    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1

    documents = {}
    for name in required:
        try:
            documents[name] = load_json(name)
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid JSON in .agent/{name}: {exc}")

    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1

    # ── Control-plane schema & resume workflow checks ─────────────────────────
    valid_statuses = {"COMPLETE", "IN_PROGRESS", "NOT_STARTED", "BLOCKED", "VERIFICATION_FAILED"}

    # 1. brain.json checks
    brain_doc = documents.get("brain.json", {})
    required_brain_keys = {"project", "architecture", "entrypoints", "navigation", "critical_rules", "current_phase", "next_action", "verification_commands"}
    missing_brain_keys = required_brain_keys - brain_doc.keys()
    if missing_brain_keys:
        errors.append(f"brain.json lacks required keys: {sorted(missing_brain_keys)}")
    if not brain_doc.get("next_action"):
        errors.append("brain.json has empty next_action instruction")

    # 2. task_state.json checks
    task_doc = documents.get("task_state.json", {})
    required_task_keys = {"phase", "status", "last_known_commit", "last_updated"}
    missing_task_keys = required_task_keys - task_doc.keys()
    if missing_task_keys:
        errors.append(f"task_state.json lacks required keys: {sorted(missing_task_keys)}")

    task_status = task_doc.get("status")
    if task_status not in valid_statuses:
        errors.append(f"task_state.json has invalid status: {task_status!r}; expected one of {sorted(valid_statuses)}")

    v_items = task_doc.get("verification_items", {})
    unfinished_v_items = [
        k for k, v in v_items.items()
        if isinstance(v, dict) and v.get("status") in ("IN_PROGRESS", "BLOCKED", "VERIFICATION_FAILED", "NOT_STARTED")
    ]
    if task_status == "COMPLETE" and unfinished_v_items:
        errors.append(f"task_state.json is marked COMPLETE while verification items are unfinished: {unfinished_v_items}")

    for k, v in v_items.items():
        if isinstance(v, dict):
            st = v.get("status")
            if st not in valid_statuses:
                errors.append(f"Verification item {k} has invalid status {st!r}")

    if task_status != "COMPLETE" and not task_doc.get("active_task") and not brain_doc.get("next_action"):
        errors.append("task_state.json is incomplete but has neither active_task nor next_action")

    # 3. architecture.json path checks
    arch_doc = documents.get("architecture.json", {})
    for comp_name, comp_info in arch_doc.get("components", {}).items():
        if isinstance(comp_info, dict) and "path" in comp_info:
            cpath = ROOT / comp_info["path"]
            if not cpath.exists():
                errors.append(f"architecture.json component {comp_name!r} path does not exist: {comp_info['path']}")

    # 4. Snapshot consistency check
    snap_path = AGENT / "snapshots" / "phase-2-verification.json"
    if snap_path.is_file():
        try:
            with snap_path.open(encoding="utf-8") as handle:
                snap_doc = json.load(handle)
            snap_status = snap_doc.get("status")
            if snap_status and task_status and str(snap_status).upper() != str(task_status).upper():
                errors.append(f"task_state.json status ({task_status}) contradicts snapshot status ({snap_status})")
        except json.JSONDecodeError as exc:
            errors.append(f"phase-2-verification.json has invalid JSON: {exc}")

    registry = documents["factor_registry.json"]
    factors = registry.get("factors", [])
    expected_fields = {"id", "name", "axis", "module", "function", "score_weight", "value_type", "database_field", "frontend_key"}
    registry_ids = [factor.get("id") for factor in factors]
    duplicate_ids = sorted(identifier for identifier, count in Counter(registry_ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"Duplicate registry factor IDs: {duplicate_ids}")
    for index, factor in enumerate(factors):
        missing = expected_fields - factor.keys()
        if missing:
            errors.append(f"Registry factor at index {index} lacks fields: {sorted(missing)}")

    executable = executable_factors()
    executable_ids = set(executable)
    registry_id_set = set(registry_ids)
    missing_registry = sorted(executable_ids - registry_id_set)
    orphan_registry = sorted(registry_id_set - executable_ids)
    if missing_registry:
        errors.append(f"Undocumented active factors: {missing_registry}")
    if orphan_registry:
        errors.append(f"Orphaned registry factors: {orphan_registry}")

    audit_columns = class_fields(MODELS, "Audit")
    api_fields = class_fields(SCHEMAS, "AuditResponse")
    if "audit_results" not in api_fields:
        errors.append("AuditResponse does not expose audit_results")
    score_config = assignment_dict(CONFIG, "TEST_SCORES")
    known_score_ids = {ast.literal_eval(key) for key in score_config.keys}

    missing_db_columns: list[str] = []
    missing_modules: list[str] = []
    missing_functions: list[str] = []
    unknown_score_ids: list[str] = []
    for factor in factors:
        module_path = ROOT / factor["module"]
        if not module_path.is_file():
            missing_modules.append(factor["id"])
        elif factor["function"] not in module_functions(module_path):
            missing_functions.append(factor["id"])
        column = factor["database_field"]
        if column is not None and column not in audit_columns:
            missing_db_columns.append(factor["id"])
        if factor["id"].rsplit(".", 1)[1] not in known_score_ids:
            unknown_score_ids.append(factor["id"])

    for label, values in (("missing modules", missing_modules), ("missing functions", missing_functions), ("missing database fields", missing_db_columns), ("unknown score IDs", unknown_score_ids)):
        if values:
            errors.append(f"{label}: {sorted(values)}")

    ui_keys = frontend_keys()
    registry_driven_ui = "__registry_driven__" in ui_keys
    frontend_missing = [] if registry_driven_ui else sorted(factor["id"] for factor in factors if factor["frontend_key"] is None)
    invalid_frontend_keys = [] if registry_driven_ui else sorted(factor["id"] for factor in factors if factor["frontend_key"] is not None and factor["frontend_key"] not in ui_keys)
    if invalid_frontend_keys:
        errors.append(f"Registry frontend keys absent from Audits.jsx: {invalid_frontend_keys}")
    if frontend_missing:
        warnings.append(f"Audits.jsx does not render {len(frontend_missing)} executable factors: {frontend_missing}")

    no_direct_column = sorted(factor["id"] for factor in factors if factor["database_field"] is None)
    if no_direct_column:
        warnings.append(f"No dedicated Audit column for {len(no_direct_column)} factors; each remains in audit_results JSON: {no_direct_column}")

    payload = {
        "valid": not errors,
        "strict_valid": not errors and not frontend_missing,
        "counts": {
            "code_factors": len(executable_ids),
            "registry_factors": len(registry_id_set),
            "db_factors_via_audit_results": len(registry_id_set) if "audit_results" in audit_columns else 0,
            "db_direct_factor_columns": len(registry_id_set) - len(no_direct_column),
            "api_factors_via_audit_results": len(registry_id_set) if "audit_results" in api_fields else 0,
            "frontend_factor_rows": len(registry_id_set) if registry_driven_ui else len(ui_keys),
            "pdf_factors_dynamic": len(registry_id_set)
        },
        "missing_factors": missing_registry,
        "duplicate_factors": duplicate_ids,
        "orphan_factors": orphan_registry,
        "broken_mappings": errors,
        "warnings": warnings
    }
    print(json.dumps(payload, indent=2))
    return 1 if errors or (strict and frontend_missing) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="Print the current parity report (default behavior).")
    parser.add_argument("--strict", action="store_true", help="Fail for known cross-layer coverage gaps; suitable for future CI.")
    args = parser.parse_args()
    sys.exit(report(strict=args.strict))
