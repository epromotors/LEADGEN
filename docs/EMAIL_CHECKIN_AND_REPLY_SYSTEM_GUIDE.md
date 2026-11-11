# LeadGen OS — System Context & Email Checkin Architecture Guide
> **Audience**: AI Agents, Autonomous Coding Agents, and LeadGen OS Core Developers  
> **Source of Truth**: `backend/app/engines/reply_engine.py`, `backend/app/routers/replies.py`, `backend/app/services/suppression_service.py`, `frontend/src/pages/Inbox.jsx`

---

## 1. System Overview: What is LeadGen OS?

**LeadGen OS** is an automated, autonomous B2B client acquisition platform designed to find businesses with poor or missing digital presence, audit their websites, verify contacts, and conduct highly targeted, compliant cold outreach.

### The Core Operational Loop
```
[ Prospect Sourcing ] ──> Google Places / Custom Scrapers (Niches, Local SMBs)
          │
          ▼
[ Technical Audit ]   ──> Headless Chromium / Lighthouse / Security / Mobile / Broken Links
          │
          ▼
[ Email Association ] ──> Domain Matching, MX Validation, Hunter/Snov Fallbacks, Association Gates
          │
          ▼
[ Smart Outreach ]    ──> Segment-specific email generation (No Website, Broken, Outdated, SEO, Redesign)
          │
          ▼
[ Email Checkin ]     ──> IMAP SSL listener continuously ingests responses & bounces
          │
     ┌────┴───────────────────────────┬───────────────────────────┐
     ▼                                ▼                           ▼
[ Converted Leads ]          [ Soft Bounces / OOO ]      [ Opt-Outs & Hard Bounces ]
(Hot Intent -> Email 2)      (Preserved for follow-up)   (Permanent Global Suppression)
```

Without the **Email Checkin** layer, the outreach system is blind: it could blast messages to invalid addresses, ignore prospects saying "YES", and spam recipients who demanded to be removed.

---

## 2. Why Do We Need the Email Checkin System?

The Email Checkin system (`/inbox` and `reply_engine.py`) serves four mission-critical functions:

### A. Closing the Revenue Loop (Lead Conversion)
Cold outreach only generates revenue when interested prospects are identified immediately.
- When a prospect replies *"Yes, send me the details"*, *"What's the price?"*, or *"Please share the blueprint"*, the system immediately promotes the lead to **`LeadStatus.converted`**.
- It records their message snippet and unlocks **Email 2 Proposals** (personalized website redesign / modernization proposals) in the operator UI.

### B. Legal Compliance (CAN-SPAM, GDPR, India IT Act)
Zero-tolerance compliance for opt-out requests is mandatory:
- When a recipient replies *"Stop"*, *"Unsubscribe"*, or *"Remove me"*, the checkin engine automatically writes their address to the **permanent `suppression_list`** table and deletes their active records from the lead database.
- Any future campaign run will unconditionally skip this address across all niches and domains.

### C. Sender Reputation & Deliverability Protection
High bounce rates quickly trigger mailbox bans from Google Workspace, Microsoft 365, and Hostinger:
- Hard bounces (550 Mailbox Not Found / Invalid User) are ingested via mailer-daemon notifications.
- The checkin engine extracts the original target recipient, adds them to global suppression, and purges the lead. This prevents repeated sending attempts that destroy domain reputation.

### D. Campaign Sequence Interlocking
- Cold outreach sequences must immediately halt for a lead once they respond.
- The checkin system sets `lead.replied_at` and `lead.reply_type`, which the campaign scheduler checks before dispatching any follow-up emails.

---

## 3. How Email Checkin Works: Technical Architecture

### 1. IMAP Ingestion (`backend/app/engines/reply_engine.py`)
- **Connection**: Uses Python's standard `imaplib.IMAP4_SSL` to connect to `imap.hostinger.com:993`.
- **Credentials**: Reads the primary sender credentials from `settings.SMTP_SENDERS`.
- **Target Folders**: Scans both `INBOX` and `INBOX.Spam` (ensuring spam-filtered auto-replies or bounces are still caught).
- **Fetch Strategy**: Queries `UNSEEN` messages, parses MIME multipart bodies into plain text, extracts headers (`Subject`, `From`, `To`, `X-Original-To`), and immediately marks the processed emails with the `\Seen` flag so they are not re-processed.

### 2. Multi-Stage Classification Cascade
The engine applies a strict deterministic priority order:

$$\mathbf{Hard\ Bounce} \longrightarrow \mathbf{Soft\ Bounce\ (OOO)} \longrightarrow \mathbf{STOP\ /\ Unsubscribe} \longrightarrow \mathbf{Positive\ Intent} \longrightarrow \mathbf{Other}$$

```
                                  [ Incoming Email ]
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               │
     Is it a Hard Bounce?                                         │
     (mailer-daemon, postmaster, 550, user unknown)               │
          │                   │                                   │
         YES                  NO                                  │
          │                   ▼                                   │
          │          Is it a Soft Bounce?                         │
          │          (Out of office, away, vacation)              │
          │               │                   │                   │
          │              YES                  NO                  │
          │               │                   ▼                   │
          │               │          Is it an Unsubscribe?        │
          │               │          (stop, remove me, opt out)   │
          │               │               │                   │   │
          │               │              YES                  NO  │
          │               │               │                   ▼   │
          │               │               │          Is it Positive?
          │               │               │          (yes, interested, quote)
          │               │               │               │       │
          │               │               │              YES      NO
          ▼               ▼               ▼               ▼       ▼
    [ HARD BOUNCE ]  [ SOFT BOUNCE ]   [ STOP / UNSUB ] [ POSITIVE ] [ OTHER ]
```

#### Exact Classification Criteria
1. **Hard Bounce (`bounce`)**:
   - Sender matches: `mailer-daemon`, `postmaster`, `mail delivery subsystem`, `no-?reply@`.
   - Body/Subject phrases: `delivery status notification`, `undeliverable`, `mail delivery failed`, `user does not exist`, `mailbox not found`, `550`, `551`, `552`, `553`.
   - *Target Resolution*: Resolves target recipient using headers `X-Original-To`, `Final-Recipient`, `Original-Recipient`, or body regex matching.
2. **Soft Bounce (`soft_bounce`)**:
   - Body/Subject phrases: `out of office`, `i am away`, `on leave`, `on vacation`, `auto-reply`, `automatic reply`, `will be back`, `temporarily unavailable`.
3. **STOP / Unsubscribe (`stop`)**:
   - Inbound phrases: `stop`, `unsubscribe`, `remove me`, `remove my email`, `opt out`, `do not contact`, `take me off`, `not interested`, `no thanks`.
   - Secondary check via `suppression_service.is_opt_out_intent(text)`.
4. **Positive Reply (`positive`)**:
   - Inbound phrases: `yes`, `yes!`, `interested`, `please contact`, `let's talk`, `call me`, `book`, `quote`, `send audit`, `how much`, `pricing`.
   - Specific CTA tier tags detected: `blueprint` (tier 1), `fix` (tier 2), `complete` (tier 3), `redesign` (tier 4), `guestpost` / `backlink` (tier 5), `maintain` (tier 6), `listing` / `gmb` (tier 7), `blog` / `content` (tier 8).
5. **Other / Unclassified (`other`)**:
   - Automated replies that don't indicate OOO, general inquiries, or replies from unknown senders not present in the DB.

---

## 4. Database Side-Effects & State Mutations

Every classification triggers explicit database mutations:

| Category | Table: `leads` | Table: `suppression_list` | Table: `audits` | Table: `activity_logs` |
| :--- | :--- | :--- | :--- | :--- |
| **`positive`** | `status = 'converted'`<br>`reply_type = 'positive'`<br>`reply_snippet = text[:500]`<br>`replied_at = now()` | *No mutation* | Preserved | Logged: `event_type='lead_converted'` (includes tier tag) |
| **`soft_bounce`** | `reply_type = 'soft_bounce'`<br>`reply_snippet = text[:500]`<br>`replied_at = now()` | *No mutation* | Preserved | Logged: `event_type='lead_soft_bounce'` |
| **`stop`** | **Permanently Deleted** | **Upserted** (`reason='unsubscribe'`, `source='inbound_reply'`) | **Permanently Deleted** | Logged: `event_type='lead_deleted_reply'` |
| **`bounce`** | **Permanently Deleted** | **Upserted** (`reason='bounce'`, `source='inbound_reply'`) | **Permanently Deleted** | Logged: `event_type='lead_deleted_reply'` |
| **`other`** | Unchanged (or reverted to `emailed` if reclassified) | *No mutation* | Preserved | Logged: `event_type='lead_reclassified'` (if manual) |

---

## 5. How the System Uses the Ingested Data

### 1. In the Web UI (`http://localhost:5174/inbox`)
- **Converted Leads Tab**: Shows all hot prospects. The operator can read the exact reply snippet and click **"Send Proposal"** to launch `Email2ComposeModal.jsx`.
- **Email 2 Generation**: Calls `GET /replies/preview-email2/{lead_id}` which dynamically renders a full HTML proposal based on the prospect's real audit deficiencies (e.g. mobile responsiveness, load speed, missing SSL, broken links). The operator can edit the proposal and send it directly via SMTP.
- **False-Positive Correction**: If an automated autoresponder says "Yes, we received your ticket", the operator can click **"Reclassify to Other"** (`PATCH /replies/reclassify/{lead_id}`). This demotes `status` from `converted` back to `emailed` and sets `reply_type='other'` without deleting the lead.
- **Sync On Demand**: Clicking **"Sync Inbox Now"** runs `POST /replies/check-now` synchronously and updates the live counters.

### 2. In Outbound Campaign Schedulers (`campaign_eligibility_service.py` & `outreach_engine.py`)
Before sending any email in any campaign batch, the engine evaluates:
1. `is_suppressed(lead.email, db)` $\rightarrow$ Must be `False`.
2. `lead.is_suppressed` $\rightarrow$ Must be `False`.
3. `lead.reply_type` $\rightarrow$ Must NOT be in `('stop', 'bounce', 'hard_bounce', 'complained')`.
4. `lead.replied_at` $\rightarrow$ Must be `None` (leads that already replied are excluded from cold sequences).

If any check fails, the lead is immediately quarantined, logged as skipped, and never emailed.

---

## 6. Directory Map & Code References

When developing or debugging this subsystem, refer to these files:

### Backend
- **Engine Logic**: [`backend/app/engines/reply_engine.py`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/backend/app/engines/reply_engine.py) (IMAP fetch, header decoding, regex pattern matching, lead deletion, conversion)
- **API Endpoints**: [`backend/app/routers/replies.py`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/backend/app/routers/replies.py) (`/check`, `/check-now`, `/converted`, `/all-replies`, `/stats`, `/preview-email2`, `/send-email2`, `/reclassify`)
- **Suppression Engine**: [`backend/app/services/suppression_service.py`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/backend/app/services/suppression_service.py) (global opt-out patterns, idempotent suppression upsert)
- **Campaign Eligibility Gates**: [`backend/app/services/campaign_eligibility_service.py`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/backend/app/services/campaign_eligibility_service.py) (pre-send suppression & reply filters)
- **Models**: [`backend/app/models.py`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/backend/app/models.py) (`Lead`, `LeadStatus`, `SuppressionList`, `ActivityLog`, `Audit`)

### Frontend
- **Main View**: [`frontend/src/pages/Inbox.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/pages/Inbox.jsx)
- **KPI Cards**: [`frontend/src/components/inbox/InboxKpiCards.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/InboxKpiCards.jsx)
- **Converted Leads Table**: [`frontend/src/components/inbox/ConvertedLeadsTable.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/ConvertedLeadsTable.jsx)
- **All Replies Table**: [`frontend/src/components/inbox/AllRepliesTable.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/AllRepliesTable.jsx)
- **Sync Controls**: [`frontend/src/components/inbox/InboxSyncPanel.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/InboxSyncPanel.jsx)
- **Reply Detail Modal**: [`frontend/src/components/inbox/ReplyDetailModal.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/ReplyDetailModal.jsx)
- **Email 2 Compose Modal**: [`frontend/src/components/inbox/Email2ComposeModal.jsx`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/components/inbox/Email2ComposeModal.jsx)
- **API Client**: [`frontend/src/api/client.js`](file:///c:/Users/LENOVO/LEADGEN-RELEASE/frontend/src/api/client.js)

---

## 7. Rules for AI Agents Modifying This System

1. **NEVER bypass suppression**: Never send an email without verifying `is_suppressed(email, db)` and `lead.is_suppressed`.
2. **Preserve Soft Bounces**: Never delete a lead classified as `soft_bounce`. Out-of-office contacts are valuable leads who are simply away temporarily.
3. **Hard-Delete on STOP and Hard Bounce**: A lead who requests removal or hard bounces must be immediately purged from the active lead database to avoid accidental re-contacting.
4. **Idempotent Suppression**: Always use `suppress_email()` so the email is stored in `suppression_list` with conflict resolution (`on_conflict_do_update`).
5. **Always maintain IMAP `\Seen` flags**: Never remove `imap.store(uid, "+FLAGS", "\\Seen")`; doing so causes mailbox loops and repeated classification of old emails.

