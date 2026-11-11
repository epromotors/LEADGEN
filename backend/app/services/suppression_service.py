"""
backend/app/services/suppression_service.py

Global Suppression List Service.

Rules (guide sections 7.1-7.2):
- Suppression is GLOBAL and PERMANENT across niches, segments, and campaigns.
- Check at queue time AND at send time.
- An opt-out reply or one-click unsubscribe must add a suppression record
  within minutes; never later than 48 hours.
- Inbound opt-out keywords: "unsubscribe", "remove me", "stop",
  "not interested", "do not contact".
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Lead, SuppressionList

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Opt-out intent detection (guide section 7.2)
# ---------------------------------------------------------------------------

OPT_OUT_PATTERNS = re.compile(
    r"\b(unsubscribe|remove\s+me|remove\s+my\s+(email|address)|"
    r"stop\s+(emailing|mailing|contacting|sending)|do\s+not\s+contact|"
    r"not\s+interested|opt\s*out|take\s+me\s+off|"
    r"please\s+remove|don.{0,5}t\s+(email|contact|send))\b",
    re.IGNORECASE,
)


def is_opt_out_intent(text: str) -> bool:
    """Return True if the text contains an unsubscribe / opt-out signal."""
    if not text or not isinstance(text, str):
        return False
    return bool(OPT_OUT_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# Suppression checks (async — for use in FastAPI routes and workers)
# ---------------------------------------------------------------------------

async def is_suppressed(email: str, db: AsyncSession) -> bool:
    """
    Check if an email address is globally suppressed.
    Called at queue time and at send time.
    """
    if not email or "@" not in email:
        return False
    result = await db.execute(
        select(SuppressionList).where(
            SuppressionList.email == email.strip().lower()
        )
    )
    return result.scalar_one_or_none() is not None


async def suppress_email(
    email: str,
    reason: str,
    source: str,
    db: AsyncSession,
    lead: Optional[Lead] = None,
) -> SuppressionList:
    """
    Add an email address to the global suppression list (idempotent).
    Also marks the corresponding Lead record as suppressed.

    Parameters
    ----------
    email  : The email address to suppress.
    reason : 'unsubscribe' | 'complaint' | 'hard_bounce' | 'manual'
    source : Where this came from, e.g. 'inbound_reply', 'one_click', 'bounce_webhook'
    db     : AsyncSession
    lead   : Optional — if provided, Lead.is_suppressed and suppression_reason are updated.
    """
    clean_email = email.strip().lower()
    now = datetime.now(timezone.utc)

    # Upsert into suppression_list (ignore conflict on email)
    stmt = pg_insert(SuppressionList).values(
        email=clean_email,
        reason=reason,
        source=source,
        created_at=now,
        updated_at=now,
    ).on_conflict_do_update(
        index_elements=["email"],
        set_={"reason": reason, "source": source, "updated_at": now},
    )
    await db.execute(stmt)

    # Mark the Lead record
    if lead is not None:
        lead.is_suppressed = True
        lead.suppressed_at = now
        lead.suppression_reason = reason
        db.add(lead)

    await db.commit()

    logger.info(
        "Suppressed email '%s' reason='%s' source='%s'",
        clean_email, reason, source,
    )

    # Return the record for callers that need it
    result = await db.execute(
        select(SuppressionList).where(SuppressionList.email == clean_email)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Reply classifier (guide section 7.8)
# ---------------------------------------------------------------------------

REPLY_PATTERNS = {
    "positive": re.compile(
        r"\b(interested|yes|please|send|share|call|let.s|let us|"
        r"would like|sounds good|tell me more|more info|proposal|"
        r"get\s+in\s+touch|connect|schedule|appointment|quote)\b",
        re.IGNORECASE,
    ),
    "question": re.compile(
        r"\b(what|how|when|where|which|cost|price|charges|fees|"
        r"available|availability|offer)\b.*\?",
        re.IGNORECASE,
    ),
    "objection": re.compile(
        r"\b(not\s+now|maybe\s+later|already\s+have|don.t\s+need|"
        r"no\s+thanks|no\s+thank\s+you|not\s+looking|busy|"
        r"have\s+someone|managing|handled)\b",
        re.IGNORECASE,
    ),
    "out_of_office": re.compile(
        r"\b(out\s+of\s+(the\s+)?office|on\s+leave|on\s+holiday|"
        r"away\s+from|auto.?reply|automatic\s+reply|will\s+be\s+back|"
        r"returning\s+on)\b",
        re.IGNORECASE,
    ),
}


def classify_reply(text: str) -> str:
    """
    Classify an inbound reply into one of:
    'unsubscribe' | 'positive' | 'question' | 'objection' | 'out_of_office' | 'unknown'
    """
    if not text or not isinstance(text, str):
        return "unknown"

    if is_opt_out_intent(text):
        return "unsubscribe"

    for label, pattern in REPLY_PATTERNS.items():
        if pattern.search(text):
            return label

    return "unknown"
