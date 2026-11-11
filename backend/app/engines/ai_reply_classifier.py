"""
backend/app/engines/ai_reply_classifier.py

Drop-in, AI-assisted replacement for the keyword cascade in reply_engine.py.

Pipeline (cheapest first):
  1. Structural  : DSN bounce parsing + auto-reply headers
  2. Strict rules: unambiguous, short STOP messages only (on QUOTE-STRIPPED text)
  3. Local LLM   : intent understanding via free Ollama (qwen2.5:3b, optional 7b escalation)
  4. Fallback    : conservative rules -> "needs_review" if the LLM is unavailable

Usage inside reply_engine.py (per fetched message):

    from app.engines.ai_reply_classifier import classify_reply, plan_actions

    msg = email.message_from_bytes(raw_bytes)
    result = classify_reply(
        msg,
        campaign_context={"subject": sent_subject, "segment": lead.segment},
    )
    plan = plan_actions(result)
    # then apply `plan` to the DB (see plan_actions docstring)
    # ALWAYS keep: imap.store(uid, "+FLAGS", "\\Seen")
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from email.message import Message
from email.utils import parseaddr
from typing import Optional

log = logging.getLogger(__name__)

# 100% free: local LLM served by Ollama (https://ollama.com). No API key, no cost.
def _cfg(name: str, default: str = "") -> str:
    """Read a setting from os.environ first, then from the app's pydantic Settings.
    (pydantic reads backend/.env into `settings` but does NOT export it to os.environ.)"""
    v = os.getenv(name)
    if v not in (None, ""):
        return v
    try:
        from app.config import settings  # type: ignore
        v = getattr(settings, name, None)
        return str(v) if v not in (None, "") else default
    except Exception:
        return default


ESCALATE_BELOW = 0.70        # fast-model confidence below this -> ask strong model (if set)
DESTRUCTIVE_MIN_CONF = 0.85  # below this, never purge data automatically
MAX_PAUSE_DAYS = 180         # never let a (possibly hallucinated) date pause a lead longer
# Small local models are less reliable, so data is only PURGED on these sources:
PURGE_TRUSTED_SOURCES = ("dsn", "rules")


class ReplyCategory(str, Enum):
    HOT = "hot_interest"          # wants details / pricing / call -> converted
    QUESTION = "question"         # asks something about the offer (warm) -> converted
    REFERRAL = "referral"         # "talk to my colleague X"
    NOT_NOW = "not_now"           # "contact me next quarter"
    OOO = "out_of_office"         # human away, auto message
    AUTO_REPLY = "auto_reply"     # ticket ack / generic autoresponder
    SOFT_BOUNCE = "soft_bounce"   # temporary delivery failure (4.x.x, mailbox full)
    HARD_BOUNCE = "hard_bounce"   # permanent failure (5.1.x, user unknown)
    UNSUBSCRIBE = "unsubscribe"   # explicit removal request
    NOT_INTERESTED = "not_interested"  # polite no, no legal opt-out wording
    COMPLAINT = "complaint"       # spam complaint / legal threat
    WRONG_PERSON = "wrong_person"
    OTHER = "other"               # unclear -> human review


# The existing UI, /replies/stats and eligibility checks understand ONLY the legacy
# reply_type vocabulary: positive | soft_bounce | stop | bounce | complained | other.
# Store the legacy value in leads.reply_type and the fine-grained value in reply_category.
LEGACY_REPLY_TYPE = {
    ReplyCategory.HOT: "positive",
    ReplyCategory.QUESTION: "positive",
    ReplyCategory.OOO: "soft_bounce",
    ReplyCategory.SOFT_BOUNCE: "soft_bounce",
    ReplyCategory.HARD_BOUNCE: "bounce",
    ReplyCategory.UNSUBSCRIBE: "stop",
    ReplyCategory.NOT_INTERESTED: "stop",
    ReplyCategory.COMPLAINT: "complained",
}


def legacy_reply_type(cat: "ReplyCategory") -> str:
    return LEGACY_REPLY_TYPE.get(cat, "other")


def resolve_pause_until(pause: Optional[str], now: datetime) -> Optional[datetime]:
    "'+90d' or 'YYYY-MM-DD' -> tz-aware datetime. Never raises; clamps to 1..180 days\n    so a hallucinated/garbled date can't silence a lead forever."
    if not pause:
        return None
    try:
        if pause.startswith("+") and pause.endswith("d"):
            days = int(pause[1:-1])
        else:
            target = datetime.fromisoformat(pause[:10]).replace(tzinfo=timezone.utc)
            days = (target - now).days + 1
    except (ValueError, TypeError):
        days = 7
    if days < 1:
        days = 7
    return now + timedelta(days=min(days, MAX_PAUSE_DAYS))


@dataclass
class ClassificationResult:
    category: ReplyCategory
    confidence: float
    source: str                       # dsn | headers | rules | llm_fast | llm_strong | fallback
    reasoning: str = ""
    intent_score: int = 0             # 0-100 buying intent (LLM only)
    tier_tag: Optional[str] = None    # blueprint/fix/complete/redesign/...
    return_date: Optional[str] = None  # ISO date for OOO / not_now
    referral_email: Optional[str] = None
    bounced_recipient: Optional[str] = None
    needs_review: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d


# --------------------------------------------------------------------------
# Text extraction helpers
# --------------------------------------------------------------------------
_QUOTE_MARKERS = [
    re.compile(r"^\s*>"),
    re.compile(r"^\s*On .{5,120}wrote:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.I),
    re.compile(r"^\s*_{5,}\s*$"),
    re.compile(r"^\s*From:\s.+", re.I),
    re.compile(r"^\s*Sent from my ", re.I),
    re.compile(r"^\s*(Get )?Outlook for ", re.I),
]


def extract_text(msg: Message) -> str:
    """Return best-effort plain text of a message (HTML stripped as fallback)."""
    plain, html = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if ctype == "text/plain" else html).append(text)
    if plain:
        return "\n".join(plain)
    raw = "\n".join(html)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"[ \t]+", " ", raw)


def strip_quoted(text: str) -> str:
    """Keep only the NEW reply text; drop quoted original email and signatures.
    This is what prevents your own unsubscribe footer from being read as a STOP."""
    kept = []
    for line in text.splitlines():
        if any(p.match(line) for p in _QUOTE_MARKERS):
            break
        kept.append(line)
    return "\n".join(kept).strip()


# --------------------------------------------------------------------------
# Layer 1: structural detection (DSN + headers)
# --------------------------------------------------------------------------
_STATUS_RE = re.compile(r"Status:\s*([245])\.(\d{1,3})\.(\d{1,3})", re.I)
_BODY_STATUS_RE = re.compile(r"\b([45])\.(\d{1,2})\.(\d{1,2})\b")
_FINAL_RCPT_RE = re.compile(
    r"(?:Final|Original)-Recipient:\s*(?:rfc822;)?\s*<?([\w.+-]+@[\w.-]+\.\w+)>?", re.I
)
_FAILED_RE = re.compile(r"X-Failed-Recipients:\s*<?([\w.+-]+@[\w.-]+\.\w+)>?", re.I)
_OOO_RE = re.compile(
    r"out of (the )?office|away from (my|the) (desk|office)|on (annual )?(leave|vacation|holiday)|"
    r"will (be back|return)|limited access to (email|mail)|auto-?reply|automatic reply",
    re.I,
)


def _map_dsn_status(cls: str, subj: str, detail: str) -> ReplyCategory:
    """RFC 3463 enhanced status codes -> category."""
    if cls == "4":
        return ReplyCategory.SOFT_BOUNCE
    # class 5
    if subj == "2":          # 5.2.x mailbox full / disabled / too large
        return ReplyCategory.SOFT_BOUNCE
    if subj == "7":          # 5.7.x policy / spam block: OUR problem, not a dead address
        return ReplyCategory.SOFT_BOUNCE
    return ReplyCategory.HARD_BOUNCE  # 5.1.x unknown user, 5.4.x routing etc.


def structural_detect(msg: Message, raw_text: str) -> Optional[ClassificationResult]:
    sender = parseaddr(msg.get("From", ""))[1].lower()
    ctype = (msg.get_content_type() or "").lower()
    is_dsn = ctype == "multipart/report" or any(
        p.get_content_type() == "message/delivery-status" for p in msg.walk()
    )
    looks_like_mta = bool(re.search(r"mailer-daemon|postmaster|mail delivery", sender, re.I))

    if is_dsn or looks_like_mta:
        blob = ""
        for part in msg.walk():
            if part.get_content_type() in ("message/delivery-status", "text/plain"):
                pl = part.get_payload(decode=False)
                if isinstance(pl, list):  # delivery-status is parsed into sub-messages
                    blob += "\n".join(str(p) for p in pl)
                elif isinstance(pl, str):
                    blob += "\n" + pl
        blob = blob or raw_text
        m = _STATUS_RE.search(blob) or _BODY_STATUS_RE.search(blob)
        rcpt_m = _FINAL_RCPT_RE.search(blob) or _FAILED_RE.search(blob) \
            or _FAILED_RE.search(str(msg))
        rcpt = rcpt_m.group(1).lower() if rcpt_m else (msg.get("X-Original-To") or None)
        if m:
            cat = _map_dsn_status(m.group(1), m.group(2), m.group(3))
            return ClassificationResult(
                cat, 0.97, "dsn",
                f"DSN status {m.group(1)}.{m.group(2)}.{m.group(3)}",
                bounced_recipient=rcpt,
            )
        if is_dsn:  # DSN with no parsable code: let LLM look, but remember it's a bounce
            return None

    # Auto-reply headers (RFC 3834 + vendor headers)
    auto = (msg.get("Auto-Submitted", "no").lower() != "no") \
        or msg.get("X-Autoreply") or msg.get("X-Autorespond") \
        or (msg.get("Precedence", "").lower() in ("auto_reply", "bulk", "junk")) \
        or msg.get("X-Auto-Response-Suppress")
    if auto:
        cat = ReplyCategory.OOO if _OOO_RE.search(raw_text) else ReplyCategory.AUTO_REPLY
        return ClassificationResult(cat, 0.92, "headers", "Auto-reply headers present")
    return None


# --------------------------------------------------------------------------
# Layer 2: strict rules (only unambiguous legal opt-outs)
# --------------------------------------------------------------------------
_STRICT_STOP = re.compile(
    r"^\W*(please\s+)?(stop|unsubscribe|remove me|remove my (e-?mail|address)|opt[- ]?out|"
    r"do not (contact|email) me|take me off( (your|the) list)?|unsubscribe me)\W*$",
    re.I,
)


def strict_rules(new_text: str) -> Optional[ClassificationResult]:
    if len(new_text.split()) > 25:
        return None
    first = next((l for l in new_text.splitlines() if l.strip()), "")
    if _STRICT_STOP.match(first.strip()):
        return ClassificationResult(ReplyCategory.UNSUBSCRIBE, 0.97, "rules",
                                    "Short explicit opt-out phrase")
    return None


# --------------------------------------------------------------------------
# Layer 3: LLM
# --------------------------------------------------------------------------
_SYSTEM = """You classify replies to B2B cold outreach emails (web design / audit / SEO services).
Classify ONLY the prospect's NEW message, using the context just to interpret it.

Categories:
- hot_interest: wants details, pricing, a call, a quote, the audit/blueprint, or says yes in any wording or language
- question: asks something about the offer, scope, process, or who we are (warm, engaged)
- referral: points us to another person/email ("talk to our marketing head")
- not_now: interested in principle but later ("reach out in Q2", "after the festival season")
- out_of_office: a person is away (auto message)
- auto_reply: generic autoresponder / ticket acknowledgement / receipt confirmation, NOT a human decision
- soft_bounce: temporary delivery failure (mailbox full, try again later)
- hard_bounce: permanent failure (user unknown, domain not found)
- unsubscribe: asks to be removed / never contacted again (any wording, incl. legal: GDPR, CAN-SPAM)
- not_interested: polite decline without asking for removal
- complaint: angry, calls it spam, threatens legal action or reporting
- wrong_person: "I'm not the right person" / "wrong company" without giving a referral
- other: genuinely unclear

Critical rules:
- "Yes, we received your request/ticket #123" is auto_reply, NOT hot_interest.
- Sarcasm or negation ("yes, I'm SO interested", "not interested, no thanks") must be judged by meaning.
- Words in quoted original text do not count.
- If a person is out of office but ALSO writes a real message, prefer the real message.
- Mixed signals -> lower confidence, do not guess high.

Reply with ONLY a JSON object:
{"category": "...", "confidence": 0.0-1.0, "intent_score": 0-100,
 "reasoning": "<=25 words", "tier_tag": "blueprint|fix|complete|redesign|guestpost|maintain|listing|content|null",
 "return_date": "YYYY-MM-DD or null", "referral_email": "email or null"}"""


_FEWSHOT = """Examples:
Reply: "Yes please send the details, what would it cost?" -> {"category":"hot_interest","confidence":0.95,"intent_score":90,"reasoning":"asks details and cost","tier_tag":null,"return_date":null,"referral_email":null}
Reply: "Yes, we received your request. Ticket #4521 has been created." -> {"category":"auto_reply","confidence":0.95,"intent_score":0,"reasoning":"ticket acknowledgement","tier_tag":null,"return_date":null,"referral_email":null}
Reply: "Not interested, thanks." -> {"category":"not_interested","confidence":0.93,"intent_score":0,"reasoning":"polite decline","tier_tag":null,"return_date":null,"referral_email":null}
Reply: "Please contact our marketing head at neha@acme.in" -> {"category":"referral","confidence":0.92,"intent_score":40,"reasoning":"gives colleague email","tier_tag":null,"return_date":null,"referral_email":"neha@acme.in"}
Reply: "Busy now, reach out after 15 January." -> {"category":"not_now","confidence":0.9,"intent_score":35,"reasoning":"asks to retry later","tier_tag":null,"return_date":"2027-01-15","referral_email":null}
Reply: "How is this different from what my current agency does?" -> {"category":"question","confidence":0.88,"intent_score":60,"reasoning":"engaged question","tier_tag":null,"return_date":null,"referral_email":null}
"""


def _call_llm(model: str, payload: str) -> dict:
    """Local Ollama call (stdlib only, no extra pip packages)."""
    import urllib.request
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": "json",                      # forces valid JSON output
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": _SYSTEM + "\n\n" + _FEWSHOT},
            {"role": "user", "content": payload},
        ],
    }).encode()
    req = urllib.request.Request(f'{_cfg("OLLAMA_URL", "http://localhost:11434")}/api/chat', data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        text = json.loads(r.read())["message"]["content"]
    return json.loads(text)


def _parse_llm(data: dict, source: str) -> ClassificationResult:
    try:
        cat = ReplyCategory(data.get("category", "other"))
    except ValueError:
        cat = ReplyCategory.OTHER
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    tag = data.get("tier_tag")
    return ClassificationResult(
        cat, conf, source,
        str(data.get("reasoning", ""))[:200],
        intent_score=int(data.get("intent_score") or 0),
        tier_tag=None if tag in (None, "null", "") else tag,
        return_date=data.get("return_date") if data.get("return_date") not in ("null", "") else None,
        referral_email=data.get("referral_email") if data.get("referral_email") not in ("null", "") else None,
    )


def llm_classify(new_text: str, subject: str, ctx: dict) -> Optional[ClassificationResult]:
    payload = (
        f"Today: {date.today().isoformat()}\n"
        f"Our original subject: {ctx.get('subject', '')}\n"
        f"Our offer segment: {ctx.get('segment', 'unknown')}\n"
        f"Reply subject: {subject}\n"
        f"--- PROSPECT'S NEW MESSAGE ---\n{new_text[:3000]}"
    )
    try:
        res = _parse_llm(_call_llm(_cfg("REPLY_LLM_FAST_MODEL", "qwen2.5:3b"), payload), "llm_fast")
    except Exception as exc:  # Ollama not running, model missing, bad JSON ...
        log.warning("Local LLM failed (is `ollama serve` running?): %s", exc)
        return None
    strong = _cfg("REPLY_LLM_STRONG_MODEL", "")
    if strong and res.confidence < ESCALATE_BELOW:
        try:
            res = _parse_llm(_call_llm(strong, payload), "llm_strong")
        except Exception as exc:
            log.info("Strong model unavailable, keeping fast result: %s", exc)
    return res


# --------------------------------------------------------------------------
# Layer 4: conservative fallback (LLM down)
# --------------------------------------------------------------------------
_FB_POSITIVE = re.compile(
    r"\b(interested|send (me )?(the )?(details|audit|proposal|quote)|how much|pricing|"
    r"let'?s (talk|connect)|call me|please contact)\b", re.I)
_FB_NEGATION = re.compile(r"\b(not|no|isn'?t|never|don'?t|unsubscribe|stop)\b", re.I)


def fallback_classify(new_text: str) -> ClassificationResult:
    if _FB_POSITIVE.search(new_text) and not _FB_NEGATION.search(new_text) \
            and len(new_text.split()) < 60:
        return ClassificationResult(ReplyCategory.HOT, 0.6, "fallback",
                                    "keyword match, LLM unavailable", needs_review=True)
    return ClassificationResult(ReplyCategory.OTHER, 0.3, "fallback",
                                "LLM unavailable, unclear", needs_review=True)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def classify_reply(msg: Message, campaign_context: Optional[dict] = None) -> ClassificationResult:
    ctx = campaign_context or {}
    raw_text = extract_text(msg)
    new_text = strip_quoted(raw_text)
    subject = str(msg.get("Subject", ""))

    # 1. Structural (bounces, auto headers)
    res = structural_detect(msg, raw_text)
    # 2. Strict rules
    if res is None:
        res = strict_rules(new_text)
    # 3. LLM
    if res is None:
        res = llm_classify(new_text or raw_text[:1500], subject, ctx)
    # 4. Fallback
    if res is None:
        res = fallback_classify(new_text)

    # Auto-replies that contain a REAL human message: let the LLM re-judge
    if res.source == "headers" and len(new_text.split()) > 40:
        llm = llm_classify(new_text, subject, ctx)
        if llm:
            res = llm

    if res.source.startswith("llm") and res.confidence < 0.6:
        res.needs_review = True
    if res.confidence < DESTRUCTIVE_MIN_CONF and res.category in (
        ReplyCategory.UNSUBSCRIBE, ReplyCategory.HARD_BOUNCE, ReplyCategory.COMPLAINT
    ):
        res.needs_review = True
    if res.category == ReplyCategory.OTHER:
        res.needs_review = True
    return res


# --------------------------------------------------------------------------
# Action planner: category -> DB/state changes
# --------------------------------------------------------------------------
def plan_actions(res: ClassificationResult) -> dict:
    """
    Returns a declarative plan. Apply it in reply_engine.py, e.g.:

        if plan["suppress"]:      suppress_email(email, reason=plan["suppress"], source="inbound_reply", db=db)
        if plan["purge_lead"]:    delete_lead_and_audit(lead, db)      # only when confident
        if plan["set_status"]:    lead.status = plan["set_status"]
        lead.reply_type    = plan["reply_type"]
        lead.reply_snippet = text[:500]
        lead.replied_at    = now() if plan["count_as_reply"] else lead.replied_at
        if plan["pause_until"]:   lead.sequence_paused_until = plan["pause_until"]
        if plan["review_queue"]:  mark lead for the "Needs Review" tab
        log_activity(plan["event"], res.to_dict())

    Principle: SUPPRESSING is always safe and reversible. PURGING data is not,
    so purge only when confidence >= DESTRUCTIVE_MIN_CONF.
    """
    c = ReplyCategory
    confident = (res.confidence >= DESTRUCTIVE_MIN_CONF and not res.needs_review
                 and res.source in PURGE_TRUSTED_SOURCES)
    base = dict(set_status=None, reply_type=legacy_reply_type(res.category),
                reply_category=res.category.value, suppress=None,
                purge_lead=False, halt_sequence=False, pause_until=None,
                count_as_reply=False, review_queue=res.needs_review,
                event=f"reply_{res.category.value}")

    if res.category in (c.HOT, c.QUESTION):
        base.update(set_status="converted", halt_sequence=True, count_as_reply=True,
                    event="lead_converted")
    elif res.category == c.REFERRAL:
        base.update(halt_sequence=True, count_as_reply=True, review_queue=True,
                    event="lead_referral")           # create new lead from res.referral_email
    elif res.category == c.NOT_NOW:
        base.update(halt_sequence=True, count_as_reply=True,
                    pause_until=res.return_date or "+90d", event="lead_snoozed")
    elif res.category == c.OOO:
        base.update(pause_until=res.return_date or "+7d", event="lead_ooo")  # NOT a real reply
    elif res.category == c.AUTO_REPLY:
        base.update(event="reply_auto_ignored")      # no state change
    elif res.category == c.SOFT_BOUNCE:
        base.update(event="lead_soft_bounce")        # retry later; after 3 -> treat as hard
    elif res.category == c.HARD_BOUNCE:
        base.update(suppress="bounce", purge_lead=confident, halt_sequence=True,
                    event="lead_deleted_reply" if confident else "lead_bounce_review")
    elif res.category == c.UNSUBSCRIBE:
        base.update(suppress="unsubscribe", purge_lead=confident, halt_sequence=True,
                    event="lead_deleted_reply" if confident else "lead_unsub_review")
    elif res.category == c.COMPLAINT:
        base.update(suppress="complained", halt_sequence=True, review_queue=True,
                    event="lead_complaint")          # keep record as legal evidence
    elif res.category in (c.NOT_INTERESTED, c.WRONG_PERSON):
        base.update(suppress="not_interested" if res.category == c.NOT_INTERESTED else None,
                    halt_sequence=True, count_as_reply=True, event="lead_declined")
    else:  # OTHER
        base.update(halt_sequence=True, count_as_reply=True, review_queue=True,
                    event="lead_needs_review")
    return base

