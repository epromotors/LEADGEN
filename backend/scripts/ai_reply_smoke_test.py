"""
backend/scripts/ai_reply_smoke_test.py

Offline smoke test for the AI reply classifier pipeline.
Builds synthetic email.message.Message objects for each category
and calls classify_reply() with the LLM step monkey-patched out.

Usage (from repo root):
    cd backend
    python scripts/ai_reply_smoke_test.py

No DB, no IMAP, no Ollama required.
"""
import sys
from email.message import Message
from pathlib import Path

# ── Make sure the app package is importable when run from backend/ ───────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import classifier (must have no import-time side effects) ────────────────
from app.engines.ai_reply_classifier import (  # noqa: E402
    classify_reply,
    plan_actions,
    ClassificationResult,
    ReplyCategory,
)
import app.engines.ai_reply_classifier as _clf_mod  # noqa: E402


# ── Monkey-patch llm_classify so we never hit Ollama ────────────────────────
def _mock_llm(text: str, subject: str = "", campaign_context: dict = None):
    """Returns None so the pipeline falls through to keyword fallback."""
    return None


_clf_mod.llm_classify = _mock_llm  # type: ignore


# ── Helper: build a minimal email.message.Message ────────────────────────────
def _make_msg(
    subject: str = "",
    body: str = "",
    *,
    auto_submitted: str = "",
    precedence: str = "",
    x_autoreply: str = "",
    x_failed_recipients: str = "",
    final_recipient: str = "",
) -> Message:
    msg = Message()
    msg["Subject"] = subject
    msg["From"] = "test@example.com"
    msg["In-Reply-To"] = "<outgoing-123@acme.com>"
    msg.set_payload(body)
    msg.set_type("text/plain")
    if auto_submitted:
        msg["Auto-Submitted"] = auto_submitted
    if precedence:
        msg["Precedence"] = precedence
    if x_autoreply:
        msg["X-Autoreply"] = x_autoreply
    if x_failed_recipients:
        msg["X-Failed-Recipients"] = x_failed_recipients
    if final_recipient:
        msg["Final-Recipient"] = final_recipient
    return msg


# ── Test scenarios ────────────────────────────────────────────────────────────
# (description, subject, body, extra_kwargs for _make_msg)
SCENARIOS = [
    ("STOP keyword (strict rules)",
     "Re: your offer",
     "STOP",
     {}),

    ("Unsubscribe word (strict rules)",
     "Re: outreach",
     "Please unsubscribe me from this list.",
     {}),

    ("Not interested (strict rules)",
     "Re: proposal",
     "not interested",
     {}),

    ("Hard bounce (auto_submitted header)",
     "Delivery Status Notification",
     "5.1.1 The email account that you tried to reach does not exist.",
     dict(auto_submitted="auto-replied",
          x_failed_recipients="bad@domain.com",
          final_recipient="rfc822; bad@domain.com")),

    ("Soft bounce (auto_submitted + 4.x.x)",
     "Delivery Status Notification",
     "4.2.2 Mailbox full — temporary failure",
     dict(auto_submitted="auto-replied",
          x_failed_recipients="full@domain.com")),

    ("Out-of-office (Auto-Submitted: auto-replied)",
     "Out of Office: Re: proposal",
     "I am out of the office until Dec 1st and will respond then.",
     dict(auto_submitted="auto-replied")),

    ("Generic auto-reply (Precedence: bulk)",
     "Auto: Re: your email",
     "Thank you for your email. We will respond within 24 hours.",
     dict(precedence="bulk")),

    ("Positive interest (keyword fallback)",
     "Re: proposal",
     "Yes, I am very interested in learning more. Can we schedule a call?",
     {}),

    ("Question (keyword fallback)",
     "Re: offer",
     "Can you tell me more about your pricing and what is included?",
     {}),

    ("Not-now / later (keyword fallback)",
     "Re: follow up",
     "We are not in the market right now but check back in Q2.",
     {}),

    ("Referral (keyword fallback)",
     "Re: proposal",
     "You should actually speak to my colleague John at john@example.com about this.",
     {}),

    ("Wrong person (keyword fallback)",
     "Re: offer",
     "I think you have the wrong person. I am not involved in purchasing decisions.",
     {}),

    ("Complaint (keyword fallback)",
     "Re: spam",
     "This is harassment. I never opted in. I will report you to the authorities.",
     {}),
]


# ── Run and format results ────────────────────────────────────────────────────
def run():
    COL = [34, 20, 10, 10, 8, 8, 9]
    HDR = ["Scenario", "category", "source", "conf", "suppress", "purge", "nds_rvw"]

    def row(*cells):
        parts = [str(v)[:w].ljust(w) for v, w in zip(cells, COL)]
        print("  ".join(parts))

    sep = "─" * (sum(COL) + 2 * len(COL))

    print()
    print("AI Reply Classifier — Offline Smoke Test (LLM patched out)")
    print(sep)
    row(*HDR)
    print(sep)

    for desc, subj, body, kwargs in SCENARIOS:
        msg = _make_msg(subject=subj, body=body, **kwargs)
        res: ClassificationResult = classify_reply(msg)
        plan = plan_actions(res)

        conf_str = f"{res.confidence:.0%}" if res.confidence is not None else "—"
        row(
            desc,
            res.category.value,
            res.source,
            conf_str,
            plan.get("suppress") or "—",
            "YES" if plan.get("purge_lead") else "no",
            "YES" if (plan.get("review_queue") or res.needs_review) else "no",
        )

    print(sep)
    print()
    print("Done. No DB, IMAP, or Ollama calls made.")
    print()


if __name__ == "__main__":
    run()
