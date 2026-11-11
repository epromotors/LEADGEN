# AI Reply Classifier — Operator Runbook

## Overview

The AI reply classifier is a 4-layer pipeline that sits behind a `REPLY_AI_MODE` feature flag in `backend/.env`.
It is **fully reversible** at any time by flipping one env var — no DB changes needed to roll back.

```
Incoming email
  1. Structural  : DSN bounce parsing (5.1.x hard, 4.x/5.2.x soft) + auto-reply headers  [deterministic]
  2. Strict rules: short, unambiguous STOP/unsubscribe on quote-stripped text only         [deterministic]
  3. Local LLM   : Ollama qwen2.5:3b → JSON category + confidence                        [free, local]
  4. Fallback    : conservative keywords → "needs_review" if LLM is down                 [safe default]
```

**Files changed:** `reply_engine.py`, `ai_reply_classifier.py`, `campaign_eligibility_service.py`, `replies.py`, `models.py`, `config.py`, migration `v8_0_0_ai_reply_columns.sql`

---

## Mode Switch

Set `REPLY_AI_MODE` in `backend/.env` and restart the backend (`uvicorn` / Docker):

| Mode | Behaviour |
|------|-----------|
| `off` | Legacy keyword classifier only. AI code path is never entered. Zero risk. |
| `shadow` | AI runs and logs to `activity_log` (`event_type = shadow_*`) but **does not change** lead state. Legacy result still applied. Use this to validate accuracy before going live. |
| `on` | AI drives all DB state changes. Legacy runs only if AI raises an exception. `needs_review` leads are quarantined from outreach until an operator clears them. |

**Emergency rollback (30 seconds):**
```bash
# 1. Set REPLY_AI_MODE=off in .env and restart
# 2. That's it — no DB changes needed
# (If you want to revert code too, use git revert, never git reset --hard)
```

---

## Installing Ollama (one-time)

```bash
# Windows
winget install Ollama.Ollama   # or download from https://ollama.ai

# Pull the model
ollama pull qwen2.5:3b         # ~2 GB, runs on CPU

# Verify
ollama run qwen2.5:3b "Reply: 'Yes, interested!' — classify as: converted/question/not_interested/..."
```

The backend reads `OLLAMA_URL=http://localhost:11434`. If Ollama is on a different host, update that URL.

---

## Going from `off` → `shadow` (validation step)

1. Set `REPLY_AI_MODE=shadow` and restart.
2. Run an IMAP sync via the **Sync Inbox Now** button (or the `/replies/check-now` API).
3. Query shadow logs to compare AI vs legacy:
   ```bash
   cd backend
   python scripts/shadow_report.py   # (see below — queries activity_log)
   ```
4. Review any `shadow_disagree` rows in `activity_log`. Spot-check categories against the actual reply text.
5. When accuracy looks good (target: ≥ 85 % agreement on unambiguous categories), proceed to `on` mode.

---

## Going from `shadow` → `on`

1. Take a DB backup:
   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -Fc leadgen_release_sandbox -f "backend/backups/pre_ai_on_$(Get-Date -Format 'yyyyMMdd_HHmm').dump"
   ```
2. Set `REPLY_AI_MODE=on` and restart.
3. Monitor the **Needs Review** tab in the Inbox page for the first 24 h.
4. If any leads are incorrectly flagged, use the **Override & Un-suppress** button.

---

## Needs Review Tab — Operator Workflow

Leads appear in **Needs Review** when:
- The AI confidence is below 60 % (`source = llm*`)
- The category is `other` (classifier gave up)
- An auto-reply header was detected but the body was long enough to warrant re-review
- The bounced recipient email doesn't match the lead email (possible mis-route)

**Actions per row:**

| Button | Effect |
|--------|--------|
| **Clear** | Sets `needs_review = False`. Lead re-enters normal outreach eligibility checks. No suppression change. |
| **Override & Un-suppress** | Sets `needs_review = False` AND removes the suppression record + sets `is_suppressed = False`. Use when AI incorrectly stopped a good lead. |

After clearing, the lead's next outreach eligibility is re-evaluated normally (cooldown, quota, etc.).

---

## Reading Shadow Logs

```sql
-- Top AI categories in shadow mode
SELECT
  SPLIT_PART(event_type, '_', 2) AS category,
  COUNT(*) AS count
FROM activity_log
WHERE event_type LIKE 'shadow_%'
GROUP BY 1
ORDER BY 2 DESC;

-- Disagreements between AI and legacy
SELECT l.email, a.message, a.created_at
FROM activity_log a
JOIN leads l ON l.id = a.lead_id
WHERE a.event_type = 'shadow_disagree'
ORDER BY a.created_at DESC
LIMIT 50;
```

---

## Suppression Reason Vocabulary

| Classifier decision | `suppression_list.reason` stored |
|---------------------|----------------------------------|
| `unsubscribe` | `unsubscribe` |
| `hard_bounce` | `bounce` |
| `complaint` | `complained` |
| `not_interested` | `not_interested` |

> **Note:** The DB column `suppression_list.reason` is `VARCHAR(50)` with no CHECK constraint — all values are stored as-is. The app code uses the values above. Do not change them without updating `suppression_service.py`.

---

## New DB Columns (v8 migration)

All columns on the `leads` table, all nullable/defaulted:

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `reply_category` | `VARCHAR(30)` | NULL | AI category (e.g. `hot_interest`, `unsubscribe`) |
| `reply_confidence` | `FLOAT` | NULL | LLM confidence 0.0–1.0 |
| `reply_source` | `VARCHAR(20)` | NULL | `headers`, `rules`, `llm_fast`, `llm_strong`, `fallback` |
| `reply_reasoning` | `VARCHAR(255)` | NULL | Short human-readable LLM reasoning |
| `intent_score` | `INTEGER` | NULL | Reserved for future scoring |
| `needs_review` | `BOOLEAN` | `false` | Operator review flag — blocks automated outreach when true |
| `bounce_count` | `INTEGER` | `0` | Soft-bounce accumulator |

---

## Rollback Plan (in order of preference)

1. **Fastest:** Set `REPLY_AI_MODE=off` in `.env`, restart → zero risk, no data change.
2. **Code only:** `git revert <commit-hash>` for the specific phase commit, redeploy.
3. **Data only:** `needs_review` can be bulk-cleared: `UPDATE leads SET needs_review = false;`
4. **Full rollback:** Restore from `backend/backups/leadgen_pre_ai_reply_*.dump` (only if data corruption).

> ⚠️ **Never** run `git reset --hard` on the production branch without explicit confirmation.

