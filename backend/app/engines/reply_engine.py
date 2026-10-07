# backend/app/engines/reply_engine.py
# LeadGen OS — Email Reply Inbox Processor
#
# Connects to Hostinger IMAP (imap.hostinger.com:993 SSL), scans INBOX + Spam,
# classifies each unseen reply, and takes the appropriate action:
#
#   positive   -> mark lead status=converted, store reply_snippet
#   stop       -> delete lead + audit from DB
#   bounce     -> delete lead + audit from DB  (permanent/hard bounce only)
#   soft_bounce-> flag lead reply_type=soft_bounce, do NOT delete
#   other      -> mark as read, no action on lead

from __future__ import annotations

import email
import imaplib
import json
import logging
import re
import uuid
from datetime import datetime
from email.header import decode_header, make_header
from typing import Optional

from sqlalchemy import select, delete as sql_delete

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Lead, Audit, LeadStatus, ActivityLog

logger = logging.getLogger(__name__)

# ── IMAP connection settings ──────────────────────────────────────────────────
IMAP_HOST = "imap.hostinger.com"
IMAP_PORT = 993
IMAP_FOLDERS = ["INBOX", "INBOX.Spam"]   # try both; fall back gracefully

# ── Classification keyword lists ──────────────────────────────────────────────

_POSITIVE_KEYWORDS = [
    "yes", "yes!", "yes,", "yes.", "interested", "please contact",
    "let's talk", "lets talk", "call me", "book", "quote", "get in touch",
    "i want", "i'm interested", "i am interested", "sounds good",
    "please proceed", "go ahead", "would like", "sounds great",
    "tell me more", "how much", "what's the price", "price",
    # Tier-specific reply keywords (Email 2 CTA responses)
    "blueprint", "fix", "complete", "redesign",
    "guestpost", "guest", "backlink",
    "maintain", "maintenance",
    "listing", "gmb", "local",
    "blog", "content",
    "send", "audit", "report",
]

# Maps reply keyword → tier tag stored in ActivityLog
_TIER_KEYWORDS: dict[str, str] = {
    "blueprint": "tier1_interest",
    "fix":        "tier2_interest",
    "complete":   "tier3_interest",
    "redesign":   "tier4_interest",
    "guestpost":  "tier5_interest",
    "guest":      "tier5_interest",
    "backlink":   "tier5_interest",
    "maintain":   "tier6_interest",
    "maintenance":"tier6_interest",
    "listing":    "tier7_interest",
    "gmb":        "tier7_interest",
    "local":      "tier7_interest",
    "blog":       "tier8_interest",
    "content":    "tier8_interest",
}

_STOP_KEYWORDS = [
    "stop", "unsubscribe", "remove me", "remove my email", "opt out",
    "opt-out", "do not email", "don't email", "do not contact",
    "don't contact", "please remove", "take me off", "not interested",
    "no thanks", "no thank you",
]

_BOUNCE_KEYWORDS = [
    # Mailer-daemon subjects
    "delivery status notification",
    "undeliverable",
    "delivery failure",
    "mail delivery failed",
    "mail delivery failure",
    "failed delivery",
    "returned mail",
    "auto-submitted",
    # Body signals
    "no such user",
    "user unknown",
    "user does not exist",
    "does not exist",
    "invalid address",
    "invalid email",
    "address rejected",
    "email address could not be found",
    "permanent failure",
    "address not found",
    "recipient address rejected",
    "mailbox not found",
    "mailbox unavailable",
    "account has been disabled",
    "account does not exist",
    "550", "551", "552", "553",   # SMTP permanent error codes in bounce body
]

_SOFT_BOUNCE_KEYWORDS = [
    "out of office",
    "i am away",
    "i'm away",
    "on leave",
    "on vacation",
    "holiday",
    "auto-reply",
    "automatic reply",
    "autoreply",
    "away from",
    "will be back",
    "returning",
    "currently unavailable",
    "office closed",
    "temporarily unavailable",
]

_BOUNCE_FROM_PATTERNS = [
    r"mailer-daemon",
    r"postmaster",
    r"mail delivery subsystem",
    r"no-?reply@",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _decode_header_value(raw) -> str:
    """Safely decode an email header value to a plain string."""
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _get_body_text(msg: email.message.Message) -> str:
    """Extract plain-text body from an email message (handles multipart)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body += part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = ""
    return body[:2000]   # limit to 2000 chars for analysis


def classify_reply(subject: str, body: str, from_addr: str) -> str:
    """
    Classify an email reply into one of:
      positive | stop | bounce | soft_bounce | other

    Precedence: bounce > soft_bounce > stop > positive > other
    """
    classification, _ = classify_reply_with_tag(subject, body, from_addr)
    return classification


def classify_reply_with_tag(subject: str, body: str, from_addr: str) -> tuple[str, str]:
    """
    Returns (classification, tier_tag).
    classification: positive | stop | bounce | soft_bounce | other
    tier_tag: e.g. 'tier2_interest' or '' if no specific tier detected
    """
    subj_lower  = subject.lower().strip()
    body_lower  = body.lower()
    from_lower  = from_addr.lower()

    # 1. Hard bounce
    for pattern in _BOUNCE_FROM_PATTERNS:
        if re.search(pattern, from_lower):
            return "bounce", ""

    for kw in _BOUNCE_KEYWORDS:
        if kw in subj_lower or kw in body_lower:
            return "bounce", ""

    # 2. Soft bounce / auto-reply (OOO)
    for kw in _SOFT_BOUNCE_KEYWORDS:
        if kw in subj_lower or kw in body_lower:
            return "soft_bounce", ""

    # 3. STOP / unsubscribe
    for kw in _STOP_KEYWORDS:
        if kw in subj_lower or kw in body_lower[:500]:
            return "stop", ""

    # 4. Positive interest — check tier keywords first for a tag
    body_sample = body_lower[:500]
    for kw, tag in _TIER_KEYWORDS.items():
        if kw in subj_lower or kw in body_sample:
            return "positive", tag

    for kw in _POSITIVE_KEYWORDS:
        if kw in subj_lower or kw in body_sample:
            return "positive", ""

    return "other", ""


def _extract_original_to(headers: dict, body: str) -> Optional[str]:
    """
    Try to find the original recipient email from bounce headers (X-Original-To,
    Final-Recipient, Original-Recipient) so we can match to the right lead.
    """
    for header in ["X-Original-To", "Final-Recipient", "Original-Recipient",
                   "X-Failed-Recipients"]:
        val = headers.get(header, "")
        if val:
            # Final-Recipient: rfc822; bob@example.com
            m = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", val)
            if m:
                return m.group(0).lower()
    # Fallback: search bounce body for email addresses
    matches = re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", body[:1000])
    for m in matches:
        if not any(s in m for s in ["mailer-daemon", "postmaster", "noreply",
                                    "tebsolutions", "hostinger"]):
            return m.lower()
    return None


# ── IMAP fetch ────────────────────────────────────────────────────────────────

def _get_smtp_config() -> dict:
    """Return the first SMTP sender config from settings."""
    try:
        senders = json.loads(settings.SMTP_SENDERS)
        return senders[0] if senders else {}
    except Exception:
        return {}


def fetch_unseen_emails() -> list[dict]:
    """
    Connect to IMAP, fetch all UNSEEN messages from INBOX and Spam.
    Returns list of dicts with keys:
      uid, folder, subject, from_addr, to_addr, body, snippet, headers
    Marks each fetched message as SEEN.
    """
    config = _get_smtp_config()
    if not config:
        raise RuntimeError("No SMTP_SENDERS configured in .env")

    imap_user = config["email"]
    imap_pass = config["password"]

    results = []

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(imap_user, imap_pass)
    except Exception as e:
        raise RuntimeError(f"IMAP login failed for {imap_user}: {e}")

    for folder in IMAP_FOLDERS:
        try:
            status, _ = imap.select(folder)
            if status != "OK":
                logger.warning(f"[reply_engine] IMAP folder '{folder}' not found — skipping")
                continue

            status, data = imap.search(None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                logger.info(f"[reply_engine] No unseen emails in {folder}")
                continue

            uids = data[0].split()
            logger.info(f"[reply_engine] Found {len(uids)} unseen email(s) in {folder}")

            for uid in uids:
                try:
                    status, msg_data = imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    subject  = _decode_header_value(msg.get("Subject", ""))
                    from_raw = _decode_header_value(msg.get("From", ""))
                    to_raw   = _decode_header_value(msg.get("To", ""))
                    body     = _get_body_text(msg)

                    # Extract plain email address from "Name <email>" format
                    from_match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", from_raw)
                    from_addr  = from_match.group(0).lower() if from_match else from_raw.lower()

                    to_match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", to_raw)
                    to_addr  = to_match.group(0).lower() if to_match else to_raw.lower()

                    headers = {k: v for k, v in msg.items()}

                    results.append({
                        "uid":       uid,
                        "folder":    folder,
                        "subject":   subject,
                        "from_addr": from_addr,
                        "to_addr":   to_addr,
                        "body":      body,
                        "snippet":   body[:500].strip(),
                        "headers":   headers,
                    })

                    # Mark as SEEN immediately
                    imap.store(uid, "+FLAGS", "\\Seen")

                except Exception as e:
                    logger.warning(f"[reply_engine] Error processing UID {uid} in {folder}: {e}")

        except Exception as e:
            logger.warning(f"[reply_engine] Error with folder '{folder}': {e}")

    try:
        imap.logout()
    except Exception:
        pass

    return results


# ── DB actions ────────────────────────────────────────────────────────────────

async def _find_lead_by_email(db, email_addr: str) -> Optional[Lead]:
    """Find a lead by their email address."""
    result = await db.execute(
        select(Lead).where(Lead.email == email_addr)
    )
    return result.scalar_one_or_none()


async def _delete_lead(db, lead: Lead, reason: str) -> None:
    """Hard-delete a lead and all their audits, log the action."""
    lead_name  = lead.business_name
    lead_email = lead.email
    lead_id    = lead.id

    # Delete audits first (FK cascade may handle it, but be explicit)
    await db.execute(sql_delete(Audit).where(Audit.lead_id == lead_id))
    await db.delete(lead)

    log = ActivityLog(
        event_type="lead_deleted_reply",
        message=f"Auto-deleted: {lead_name} <{lead_email}> — {reason}",
    )
    db.add(log)
    await db.commit()
    logger.info(f"[reply_engine] Deleted lead {lead_email} — {reason}")


async def _mark_converted(db, lead: Lead, snippet: str, reply_type: str,
                           tier_tag: str = "") -> None:
    """Mark a lead as converted (positive reply), with optional tier tag."""
    lead.status       = LeadStatus.converted
    lead.reply_type   = reply_type
    lead.reply_snippet = snippet[:500]
    lead.replied_at   = datetime.utcnow()

    tag_note = f" [{tier_tag}]" if tier_tag else ""
    log = ActivityLog(
        event_type="lead_converted",
        lead_id=lead.id,
        message=(
            f"Positive reply from {lead.business_name} <{lead.email}>"
            f"{tag_note}: {snippet[:120]}"
        ),
    )
    db.add(log)
    await db.commit()
    logger.info(
        f"[reply_engine] Converted lead: {lead.email}"
        + (f" ({tier_tag})" if tier_tag else "")
    )


async def _flag_soft_bounce(db, lead: Lead, snippet: str) -> None:
    """Flag a lead as soft-bounced (OOO) — do not delete."""
    lead.reply_type    = "soft_bounce"
    lead.reply_snippet = snippet[:500]
    lead.replied_at    = datetime.utcnow()

    log = ActivityLog(
        event_type="lead_soft_bounce",
        lead_id=lead.id,
        message=f"Soft bounce / OOO from {lead.business_name} <{lead.email}>",
    )
    db.add(log)
    await db.commit()
    logger.info(f"[reply_engine] Soft-bounce flagged: {lead.email}")


# ── Main processor ────────────────────────────────────────────────────────────

async def process_replies() -> dict:
    """
    Full reply processing cycle:
      1. Fetch all unseen emails from INBOX + Spam via IMAP
      2. Classify each email
      3. Find the matching lead in DB (by from_addr or bounce original-to)
      4. Take action: convert | delete | flag | ignore

    Returns summary dict: {fetched, positive, deleted, soft_bounce, other, errors}
    """
    stats = {
        "fetched":     0,
        "positive":    0,
        "deleted":     0,
        "soft_bounce": 0,
        "other":       0,
        "errors":      0,
    }

    try:
        emails = fetch_unseen_emails()
    except Exception as e:
        logger.error(f"[reply_engine] fetch_unseen_emails failed: {e}")
        stats["errors"] += 1
        raise

    stats["fetched"] = len(emails)

    async with AsyncSessionLocal() as db:
        for em in emails:
            try:
                subject   = em["subject"]
                from_addr = em["from_addr"]
                body      = em["body"]
                snippet   = em["snippet"]
                headers   = em["headers"]

                reply_type, tier_tag = classify_reply_with_tag(subject, body, from_addr)
                logger.info(
                    f"[reply_engine] {from_addr} | {reply_type.upper()}"
                    + (f" [{tier_tag}]" if tier_tag else "")
                    + f" | '{subject[:60]}'"
                )

                # For bounces: match by original recipient, not from_addr
                if reply_type == "bounce":
                    target_email = _extract_original_to(headers, body) or from_addr
                else:
                    target_email = from_addr

                lead = await _find_lead_by_email(db, target_email)

                if reply_type == "positive":
                    if lead:
                        await _mark_converted(db, lead, snippet, "positive", tier_tag=tier_tag)
                        stats["positive"] += 1
                    else:
                        logger.debug(f"[reply_engine] Positive reply but no lead found for {target_email}")
                        stats["other"] += 1

                elif reply_type == "stop":
                    if lead:
                        await _delete_lead(db, lead, "STOP request — unsubscribed")
                        stats["deleted"] += 1
                    else:
                        logger.debug(f"[reply_engine] STOP from unknown email: {from_addr}")
                        stats["other"] += 1

                elif reply_type == "bounce":
                    if lead:
                        await _delete_lead(db, lead, f"Hard bounce — invalid email address")
                        stats["deleted"] += 1
                    else:
                        logger.debug(f"[reply_engine] Bounce for unknown address: {target_email}")
                        stats["other"] += 1

                elif reply_type == "soft_bounce":
                    if lead:
                        await _flag_soft_bounce(db, lead, snippet)
                    stats["soft_bounce"] += 1

                else:
                    stats["other"] += 1

            except Exception as e:
                logger.error(f"[reply_engine] Error processing email from {em.get('from_addr','')} : {e}")
                stats["errors"] += 1

    logger.info(f"[reply_engine] Done — {stats}")
    return stats
