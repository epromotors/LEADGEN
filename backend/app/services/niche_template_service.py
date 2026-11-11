"""
backend/app/services/niche_template_service.py

Niche-Aware Template Library Service.

Loads templates_all.json (260 templates: 26 niches × 10 segments) and
provides the authoritative lookup + subject-rotation logic per the
AGENT_GUIDE_all_batches.md sections 1-5.

Key rules enforced here:
- Templates keyed by (niche_id, segment_no, template_version).
- Subject rotated round-robin among [subject] + subject_alternatives.
- Segments 2-7 and 9 must have non-empty audit_findings.
- Segments 1 and 10 must NOT contain {domain}.
- Fail-closed: raises NicheTemplateError if any rule is violated.
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class NicheTemplateError(Exception):
    """Raised when a template cannot be loaded, validated, or rendered."""


# ---------------------------------------------------------------------------
# Segments that REQUIRE audit findings
# ---------------------------------------------------------------------------
AUDIT_REQUIRED_SEGMENTS = frozenset({2, 3, 4, 5, 6, 7, 9})

# Segments where {domain} is FORBIDDEN in body + subject
NO_DOMAIN_SEGMENTS = frozenset({1, 10})

# Allowed tokens per guide section 2 / template_generator.py
ALLOWED_TOKENS = frozenset({
    "business_name", "website", "domain",
    "audit_summary", "audit_findings", "audit_recommendations",
    "opportunity_summary", "proposal_summary",
    "suggested_service", "sender_name", "company_name", "company_website",
    # New tokens from guide section 11 / 6.1
    "city", "niche_label", "finding_count", "contact_name",
})

# Segment number → CampaignType key (matches campaign_eligibility_service.CampaignType)
SEGMENT_TO_CAMPAIGN_TYPE: Dict[int, str] = {
    1:  "no_website_design",
    2:  "broken_website_repair",
    3:  "outdated_website_modernization",
    4:  "valid_website_seo",
    5:  "valid_website_redesign",
    6:  "valid_website_link_building",
    7:  "valid_website_marketing",
    8:  "generic_first_contact",
    9:  "audit_follow_up",
    10: "public_provider_demo",
}

CAMPAIGN_TYPE_TO_SEGMENT: Dict[str, int] = {v: k for k, v in SEGMENT_TO_CAMPAIGN_TYPE.items()}


# ---------------------------------------------------------------------------
# Template library singleton
# ---------------------------------------------------------------------------

class NicheTemplateLibrary:
    """
    Thread-safe singleton that loads and caches the 260-template library.
    Keyed internally as (niche_id, segment_no) → template record.
    Multiple versions are stored as a list; the latest VERSION is used by default.
    """

    _instance: Optional["NicheTemplateLibrary"] = None
    _lock = threading.Lock()

    def __init__(self, templates: List[Dict[str, Any]]):
        # Primary index: (niche_id, segment_no) → list of template records (sorted by version)
        self._index: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        for t in templates:
            key = (t["niche_id"], t["segment_no"])
            self._index.setdefault(key, []).append(t)
        # Sort each bucket newest-first (version is a string like "1.0")
        for key in self._index:
            self._index[key].sort(key=lambda r: r.get("template_version", "0"), reverse=True)

        # Rotation state: (niche_id, segment_no) → next subject index
        self._rotation: Dict[Tuple[int, int], int] = {}
        self._rotation_lock = threading.Lock()

        logger.info(
            "NicheTemplateLibrary: loaded %d templates (%d niche×segment pairs)",
            len(templates), len(self._index),
        )

    @classmethod
    def get_instance(cls) -> "NicheTemplateLibrary":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls._load()
        return cls._instance

    @classmethod
    def _load(cls) -> "NicheTemplateLibrary":
        json_path = Path(__file__).parent.parent / "templates_all.json"
        if not json_path.exists():
            raise NicheTemplateError(
                f"templates_all.json not found at {json_path}. "
                "Run template_generator.py to regenerate it."
            )
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            raise NicheTemplateError("templates_all.json is empty or malformed.")
        return cls(data)

    @classmethod
    def reload(cls) -> None:
        """Force a reload of the library (e.g., after a template rebuild)."""
        with cls._lock:
            cls._instance = cls._load()

    def get_template(
        self,
        niche_id: int,
        segment_no: int,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return the template record for (niche_id, segment_no).
        If version is None, the latest version is returned.
        Raises NicheTemplateError if not found.
        """
        key = (niche_id, segment_no)
        bucket = self._index.get(key)
        if not bucket:
            raise NicheTemplateError(
                f"No template found for niche_id={niche_id}, segment_no={segment_no}."
            )
        if version is None:
            return bucket[0]  # newest
        for record in bucket:
            if record.get("template_version") == version:
                return record
        raise NicheTemplateError(
            f"Template version '{version}' not found for niche_id={niche_id}, segment_no={segment_no}."
        )

    def rotate_subject(self, niche_id: int, segment_no: int, template: Dict[str, Any]) -> str:
        """
        Return the next subject in round-robin rotation:
        [subject, alt1, alt2] cycling per (niche_id, segment_no).
        Guide section 6.2: all 3 subjects must be used, in rotation.
        """
        key = (niche_id, segment_no)
        pool = [template["subject"]] + list(template.get("subject_alternatives", []))
        if not pool:
            return template.get("subject", "")
        with self._rotation_lock:
            idx = self._rotation.get(key, 0)
            chosen = pool[idx % len(pool)]
            self._rotation[key] = (idx + 1) % len(pool)
        return chosen


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _find_unresolved_tokens(text: str) -> List[str]:
    return re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text)


def _substitute(text: str, context: Dict[str, str]) -> str:
    """Simple token substitution — leaves unknown tokens in place for validation."""
    for k, v in context.items():
        text = text.replace(f"{{{k}}}", str(v) if v is not None else "")
    return text


def render_niche_template(
    niche_id: int,
    segment_no: int,
    context: Dict[str, str],
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load, rotate subject, substitute tokens, and validate a niche template.

    Parameters
    ----------
    niche_id    : 1-26
    segment_no  : 1-10
    context     : token → value map (business_name, domain, audit_findings, …)
    version     : specific template version string, or None for latest

    Returns
    -------
    {
        "subject": str,
        "body": str,
        "preview": str,
        "niche_id": int,
        "niche": str,
        "segment_no": int,
        "segment_key": str,
        "template_version": str,
        "campaign_type": str,
    }

    Raises NicheTemplateError if any fail-closed rule is violated.
    """
    lib = NicheTemplateLibrary.get_instance()
    tmpl = lib.get_template(niche_id, segment_no, version)

    # Subject rotation (round-robin)
    raw_subject = lib.rotate_subject(niche_id, segment_no, tmpl)
    subject = _substitute(raw_subject, context)
    body = _substitute(tmpl["body"], context)
    preview = _substitute(tmpl.get("preview", ""), context)

    # ── Fail-closed validation ──────────────────────────────────────────
    errors: List[str] = []

    # 1. No unresolved tokens
    for field_name, field_text in [("subject", subject), ("body", body), ("preview", preview)]:
        unresolved = [t for t in _find_unresolved_tokens(field_text) if t not in ALLOWED_TOKENS]
        # Tokens not supplied (still in braces) but not in allowed list = bug
        still_present = _find_unresolved_tokens(field_text)
        if still_present:
            errors.append(
                f"Unresolved token(s) in {field_name}: "
                + ", ".join(f"{{{t}}}" for t in still_present)
            )

    # 2. audit_findings required for segments 2-7, 9
    if segment_no in AUDIT_REQUIRED_SEGMENTS:
        if not (context.get("audit_findings") or "").strip():
            errors.append(
                f"Segment {segment_no} requires non-empty {{audit_findings}} "
                "(no audit evidence stored; cannot send)."
            )

    # 3. Subject length ≤ 50 chars
    if len(subject) > 50:
        errors.append(
            f"Subject too long after substitution ({len(subject)} chars > 50): {subject!r}"
        )

    # 4. Preview ≤ 90 chars
    if len(preview) > 90:
        errors.append(
            f"Preview too long after substitution ({len(preview)} chars > 90): {preview!r}"
        )

    # 5. {domain} must not appear in segments 1 or 10
    if segment_no in NO_DOMAIN_SEGMENTS:
        domain_val = context.get("domain", "")
        if domain_val and domain_val in body:
            errors.append(
                f"Segment {segment_no} body must not contain {{domain}} value '{domain_val}'."
            )
        if domain_val and domain_val in subject:
            errors.append(
                f"Segment {segment_no} subject must not contain {{domain}} value '{domain_val}'."
            )

    if errors:
        raise NicheTemplateError(
            f"Niche template validation failed (niche={niche_id}, seg={segment_no}): "
            + " | ".join(errors)
        )

    campaign_type = SEGMENT_TO_CAMPAIGN_TYPE.get(segment_no, "generic_first_contact")

    return {
        "subject": subject,
        "body": body,
        "preview": preview,
        "niche_id": niche_id,
        "niche": tmpl.get("niche", ""),
        "segment_no": segment_no,
        "segment_key": tmpl.get("segment_key", ""),
        "template_version": tmpl.get("template_version", "1.0"),
        "audit_required": tmpl.get("audit_required", False),
        "campaign_type": campaign_type,
    }


def get_campaign_type_for_segment(segment_no: int) -> str:
    """Convert segment number to campaign_type string for the existing eligibility service."""
    return SEGMENT_TO_CAMPAIGN_TYPE.get(segment_no, "generic_first_contact")


def get_segment_for_campaign_type(campaign_type: str) -> Optional[int]:
    """Convert campaign_type string to segment number."""
    return CAMPAIGN_TYPE_TO_SEGMENT.get(campaign_type)


def list_available_niches() -> List[Dict[str, Any]]:
    """Return a list of all (niche_id, niche_name) pairs loaded in the library."""
    lib = NicheTemplateLibrary.get_instance()
    seen: Dict[int, str] = {}
    for (nid, _seg), bucket in lib._index.items():
        if nid not in seen:
            seen[nid] = bucket[0].get("niche", f"Niche {nid}")
    return [{"niche_id": nid, "niche": name} for nid, name in sorted(seen.items())]
