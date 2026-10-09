"""Canonical audit-factor contract, registry governance, and score calculation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import ast
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

logger = logging.getLogger(__name__)

FACTOR_STATES = {"PASS", "WARN", "FAIL", "N/A", "ERROR", "UNKNOWN"}
AUDIT_LIFECYCLES = {"PENDING", "RUNNING", "COMPLETE", "PARTIAL", "BLOCKED", "FAILED"}
VALID_SEVERITIES = {"critical", "high", "medium", "low", "unclassified"}
VALID_VALUE_TYPES = {"boolean", "count", "number", "duration_ms", "bytes", "list", "string", "object", "null"}
VALID_ENGINES = {"http_raw_dom", "http", "crawler"}


class FactorRegistryError(ValueError):
    """Raised when executable audit governance is inconsistent."""


def determine_lifecycle(*, homepage_ok: bool, crawl_status: str) -> str:
    """Return explicit audit evidence lifecycle without collapsing crawl errors."""
    if not homepage_ok:
        return "BLOCKED"
    if crawl_status in {"ERROR", "PARTIAL"}:
        return "PARTIAL"
    return "COMPLETE"


@dataclass
class FactorResult:
    id: str
    status: str
    value: Any = None
    value_type: str = "object"
    unit: str | None = None
    score: float = 0
    max_score: float = 0
    severity: str = "unclassified"
    confidence: float = 1.0
    message: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    threshold: dict[str, Any] = field(default_factory=dict)
    engine: str = "http_raw_dom"
    page_url: str | None = None
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: int = 0
    error: str | None = None
    fix: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def registry_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".agent" / "factor_registry.json"


def load_factor_registry() -> dict[str, Any]:
    with registry_path().open(encoding="utf-8") as handle:
        return json.load(handle)


def _registry_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {factor["id"]: factor for factor in registry.get("factors", [])}


def validate_factor_registry(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Validate the JSON registry before production execution uses it."""
    registry = registry or load_factor_registry()
    defaults = registry.get("record_defaults", {})
    factors = registry.get("factors", [])
    seen: set[str] = set()
    index: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for factor in factors:
        factor_id = factor.get("id")
        if not factor_id:
            errors.append("factor is missing id")
            continue
        if factor_id in seen:
            errors.append(f"duplicate factor id: {factor_id}")
        seen.add(factor_id)
        for key in ("axis", "module", "function", "score_weight", "value_type", "database_field", "frontend_key"):
            if key not in factor:
                errors.append(f"{factor_id}: missing mapping field {key}")
        if not factor.get("axis"):
            errors.append(f"{factor_id}: missing axis")
        if not factor.get("module") or not factor.get("function"):
            errors.append(f"{factor_id}: missing module/function")
        else:
            module_path = registry_path().parents[1] / factor["module"]
            if not module_path.is_file():
                errors.append(f"{factor_id}: missing module {factor['module']}")
            else:
                try:
                    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
                    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                    if factor["function"] not in functions:
                        errors.append(f"{factor_id}: unknown function {factor['function']}")
                except (OSError, SyntaxError) as exc:
                    errors.append(f"{factor_id}: unreadable module ({exc})")
        if factor.get("value_type") not in VALID_VALUE_TYPES:
            errors.append(f"{factor_id}: invalid value type {factor.get('value_type')}")
        if not isinstance(factor.get("score_weight"), (int, float)) or factor.get("score_weight", 0) < 0:
            errors.append(f"{factor_id}: invalid score configuration")
        severity = factor.get("severity", defaults.get("severity", "unclassified"))
        if severity not in VALID_SEVERITIES:
            errors.append(f"{factor_id}: invalid severity {severity}")
        engine = factor.get("engine", defaults.get("engine", "http_raw_dom"))
        if engine not in VALID_ENGINES:
            errors.append(f"{factor_id}: invalid engine {engine}")
        status = factor.get("status", defaults.get("status"))
        if not status:
            errors.append(f"{factor_id}: missing registry status")
        index[factor_id] = factor
    if len(index) != 62:
        errors.append(f"expected 62 factors, found {len(index)}")
    if errors:
        raise FactorRegistryError("; ".join(errors))
    return index


def normalise_legacy_result(raw: dict[str, Any], factor: dict[str, Any], page_url: str | None, duration_ms: int) -> FactorResult:
    """Adapter for existing factor modules while they migrate to native values."""
    raw = raw if isinstance(raw, dict) else {}
    status = raw.get("status", "UNKNOWN")
    if status not in FACTOR_STATES:
        status = "UNKNOWN"
    value = raw.get("value")
    value_type = factor["value_type"]
    # Native structured fields are authoritative. Legacy values remain unknown,
    # never guessed from display text by persistence or scoring code.
    if value is None and value_type == "boolean" and status in {"PASS", "FAIL"}:
        value = status == "PASS"
    return FactorResult(
        id=factor["id"], status=status, value=value, value_type=value_type,
        unit=raw.get("unit"), score=0, max_score=factor["score_weight"],
        severity=factor.get("severity", "unclassified"), confidence=raw.get("confidence", 1.0),
        message=raw.get("message", ""), evidence=raw.get("evidence", []),
        threshold=raw.get("threshold", {}), engine=factor.get("engine", "http_raw_dom"),
        page_url=page_url, duration_ms=duration_ms, error=raw.get("error"),
        fix=raw.get("fix", ""), detail=raw.get("detail", ""),
    )


def safe_execute_factor(factor: dict[str, Any], callback: Callable[[], dict[str, Any]], page_url: str | None) -> dict[str, Any]:
    """Execute one factor without letting an exception abort sibling factors."""
    started = perf_counter()
    try:
        raw = callback()
        result = normalise_legacy_result(raw, factor, page_url, round((perf_counter() - started) * 1000))
    except Exception as exc:  # isolated and observable by design
        logger.exception("Audit factor %s failed for %s", factor["id"], page_url)
        result = FactorResult(
            id=factor["id"], status="ERROR", value_type=factor["value_type"],
            max_score=factor["score_weight"], severity=factor.get("severity", "unclassified"),
            confidence=0.0, message=f"Factor execution failed: {factor['id']}.",
            engine=factor.get("engine", "http_raw_dom"), page_url=page_url,
            duration_ms=round((perf_counter() - started) * 1000), error=f"{type(exc).__name__}: {exc}",
        )
    if result.status == "PASS":
        result.score = result.max_score
    elif result.status == "WARN":
        result.score = result.max_score * 0.5
    return result.to_dict()


def compute_score(
    audit_results: dict[str, dict[str, dict[str, Any]]],
    group_weights: dict[str, float],
    registry: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Score only applicable, known structured results; N/A is excluded."""
    if not group_weights:
        raise FactorRegistryError("score configuration has no group weights")
    registry = registry or validate_factor_registry()
    weighted_sum = 0.0
    applicable_weight = 0.0
    for group, results in audit_results.items():
        if group not in group_weights:
            raise FactorRegistryError(f"unknown score group: {group}")
        applicable = [item for item in results.values() if item.get("status") != "N/A"]
        if not applicable:
            continue
        for test_id, item in results.items():
            if item.get("status") not in FACTOR_STATES:
                raise FactorRegistryError(f"invalid factor state in score input: {item.get('status')}")
            expected_id = f"{group}.{test_id}"
            if item.get("id") != expected_id:
                raise FactorRegistryError(f"factor result id mismatch: expected {expected_id}, got {item.get('id')}")
            if expected_id not in registry:
                raise FactorRegistryError(f"unknown factor id in score input: {expected_id}")
        max_points = sum(item.get("max_score", 0) for item in applicable)
        if not max_points:
            continue
        earned = sum(item.get("score", 0) for item in applicable)
        weighted_sum += earned / max_points * 100 * group_weights[group]
        applicable_weight += group_weights[group]
    return round(weighted_sum / applicable_weight) if applicable_weight else 0
