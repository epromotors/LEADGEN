"""Offline tests: no Ollama, no network, no DB. Run: pytest -q backend/tests/test_ai_reply_classifier.py"""
import email
from datetime import datetime, timedelta, timezone
import pytest
from app.engines import ai_reply_classifier as m
from app.engines.ai_reply_classifier import ReplyCategory as C

DSN = """From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: sales@mydomain.com
Subject: Delivery Status Notification (Failure)
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="B"

--B
Content-Type: text/plain

Your message could not be delivered.

--B
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; ghost@example.com
Action: failed
Status: {status}

--B--
"""

def msg(raw): return email.message_from_string(raw)

def plain(body, extra=""):
    return msg(f"From: Bob <bob@acme.com>\nTo: sales@mydomain.com\nSubject: Re: Website\n{extra}\n{body}\n")

@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(m, "llm_classify", lambda *a, **k: None)

def test_dsn_hard_bounce_extracts_recipient():
    r = m.classify_reply(msg(DSN.format(status="5.1.1")))
    assert r.category == C.HARD_BOUNCE and r.source == "dsn"
    assert r.bounced_recipient == "ghost@example.com"

@pytest.mark.parametrize("status", ["4.2.2", "5.2.2", "5.7.1"])
def test_dsn_soft_bounces(status):
    assert m.classify_reply(msg(DSN.format(status=status))).category == C.SOFT_BOUNCE

def test_noreply_sender_is_not_a_bounce():
    r = m.classify_reply(msg("From: x <no-reply@shop.com>\nSubject: Thanks\n\nHello there"))
    assert r.category not in (C.HARD_BOUNCE, C.SOFT_BOUNCE)

def test_ooo_header():
    r = m.classify_reply(plain("I am out of office until 20 Nov.", "Auto-Submitted: auto-replied\n"))
    assert r.category == C.OOO and r.source == "headers"

def test_quoted_unsubscribe_footer_is_ignored():
    body = ("Yes please send details.\n\nOn Mon, Nov 9, 2026 at 10:00 AM Sales <a@b.com> wrote:\n"
            "> Hi, to unsubscribe reply STOP\n> unsubscribe")
    new = m.strip_quoted(body)
    assert "unsubscribe" not in new.lower()
    r = m.classify_reply(plain(body))
    assert r.category != C.UNSUBSCRIBE

@pytest.mark.parametrize("t", ["Unsubscribe", "STOP", "Please remove me", "Do not contact me"])
def test_strict_stop(t):
    r = m.classify_reply(plain(t))
    assert r.category == C.UNSUBSCRIBE and r.source == "rules"

def test_stop_inside_sentence_is_not_stop():
    assert m.strict_rules("Please stop by our office tomorrow to discuss the website") is None

def test_llm_down_goes_to_review_not_purge():
    r = m.classify_reply(plain("Interested, how much would it cost?"))
    assert r.needs_review and r.source == "fallback"
    p = m.plan_actions(r)
    assert not p["purge_lead"] and p["suppress"] is None

def test_llm_unsubscribe_suppresses_but_never_purges():
    r = m.ClassificationResult(C.UNSUBSCRIBE, 0.95, "llm_fast")
    p = m.plan_actions(r)
    assert p["suppress"] == "unsubscribe" and p["purge_lead"] is False

def test_rules_unsubscribe_purges():
    p = m.plan_actions(m.ClassificationResult(C.UNSUBSCRIBE, 0.97, "rules"))
    assert p["suppress"] == "unsubscribe" and p["purge_lead"] is True

def test_dsn_hard_bounce_purges_soft_does_not():
    assert m.plan_actions(m.ClassificationResult(C.HARD_BOUNCE, 0.97, "dsn"))["purge_lead"]
    assert not m.plan_actions(m.ClassificationResult(C.SOFT_BOUNCE, 0.97, "dsn"))["purge_lead"]

def test_ooo_and_auto_reply_do_not_count_as_replies():
    for cat in (C.OOO, C.AUTO_REPLY):
        p = m.plan_actions(m.ClassificationResult(cat, 0.9, "headers"))
        assert not p["count_as_reply"] and not p["purge_lead"] and p["suppress"] is None

def test_hot_converts_and_halts():
    p = m.plan_actions(m.ClassificationResult(C.HOT, 0.9, "llm_fast"))
    assert p["set_status"] == "converted" and p["halt_sequence"] and p["count_as_reply"]


def test_legacy_reply_type_mapping_keeps_ui_working():
    cases = {C.HOT: "positive", C.QUESTION: "positive", C.OOO: "soft_bounce",
             C.SOFT_BOUNCE: "soft_bounce", C.HARD_BOUNCE: "bounce", C.UNSUBSCRIBE: "stop",
             C.NOT_INTERESTED: "stop", C.COMPLAINT: "complained", C.REFERRAL: "other",
             C.AUTO_REPLY: "other", C.OTHER: "other"}
    for cat, legacy in cases.items():
        p = m.plan_actions(m.ClassificationResult(cat, 0.9, "llm_fast"))
        assert p["reply_type"] == legacy and p["reply_category"] == cat.value

def test_resolve_pause_until_is_clamped_and_never_raises():
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    assert m.resolve_pause_until(None, now) is None
    assert m.resolve_pause_until("+90d", now) == now + timedelta(days=90)
    assert m.resolve_pause_until("2099-01-01", now) == now + timedelta(days=180)
    assert m.resolve_pause_until("garbage", now) == now + timedelta(days=7)
    assert m.resolve_pause_until("2020-01-01", now) == now + timedelta(days=7)
    assert (m.resolve_pause_until("2026-11-20", now) - now).days == 10

def test_cfg_prefers_env_and_has_safe_defaults(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://x:1")
    assert m._cfg("OLLAMA_URL", "d") == "http://x:1"
    monkeypatch.delenv("REPLY_LLM_STRONG_MODEL", raising=False)
    assert m._cfg("REPLY_LLM_STRONG_MODEL", "") == ""
