"""
maintenance_reaudit_stale.py — One-time maintenance script.

PROBLEM:
  1340 leads have has_robots=False in DB from BEFORE the robots.txt logic fix
  was deployed. Many of these sites actually have a valid robots.txt and should
  show PASS.

WHAT THIS SCRIPT DOES:
  1. Finds all leads with has_robots=False and audit_status=done
  2. For each, runs audit_robots() live against the website
  3. If LIVE returns PASS → updates has_robots=True in DB directly
     (no full re-audit needed — only the robots column is stale)
  4. Logs all changes to a CSV file

SAFETY:
  - Read-only until you pass --apply flag
  - Skips unreachable sites (connection errors)
  - Rate-limited: 2 req/sec max
  - Never touches leads with audit_status != 'done'

Usage:
  python maintenance_reaudit_stale.py          # dry-run, no DB changes
  python maintenance_reaudit_stale.py --apply  # apply DB updates
"""
import sys, time, csv, datetime
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

APPLY = "--apply" in sys.argv
DRY_RUN = not APPLY
print(f"Mode: {'DRY-RUN (no DB changes)' if DRY_RUN else 'APPLY (will update DB)'}")
print()

# ── Auditor setup ──────────────────────────────────────────────────────────────
_AUDITOR_PATH = Path(__file__).parent.parent / "auditor" / "auditor"
sys.path.insert(0, str(_AUDITOR_PATH))

import requests
from auditor.technical import audit_robots

# ── DB setup ───────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent / ".env"
db_url = None
for line in env_path.read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        db_url = line.split("=", 1)[1].strip().replace("postgresql+psycopg://", "postgresql://")
        break

import psycopg
conn = psycopg.connect(db_url)
conn.autocommit = False
cur = conn.cursor()

# ── Fetch all has_robots=False DONE leads ─────────────────────────────────────
cur.execute("""
    SELECT l.id, l.business_name, l.website, a.id as audit_id, a.updated_at
    FROM leads l
    JOIN audits a ON a.lead_id = l.id
    WHERE a.has_robots = false
      AND a.status = 'done'
      AND l.website IS NOT NULL
      AND l.website NOT LIKE 'SITE_STATUS%'
    ORDER BY a.updated_at DESC
""")
leads = cur.fetchall()
cols  = [d[0] for d in cur.description]

print(f"Found {len(leads)} leads with has_robots=False")
print()

# ── Log file ──────────────────────────────────────────────────────────────────
log_path = Path(__file__).parent / "maintenance_reaudit_log.csv"
log_rows = []

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (compatible; SEO-Audit/5.0)"

updated = 0
skipped = 0
errors  = 0

for i, row in enumerate(leads, 1):
    lead = dict(zip(cols, row))
    url  = lead["website"].rstrip("/")
    name = (lead["business_name"] or "")[:60]

    print(f"[{i:4d}/{len(leads)}] {name[:40]:40s} | {url}")

    try:
        result = audit_robots(url, session)
        live_pass = result["status"] == "PASS"
        msg = result["message"][:80]

        if live_pass:
            # DB says False, live says PASS → update
            if not DRY_RUN:
                cur.execute(
                    "UPDATE audits SET has_robots = true WHERE id = %s",
                    (lead["audit_id"],)
                )
            log_rows.append({
                "lead_id": lead["id"], "name": name, "url": url,
                "action": "UPDATED" if not DRY_RUN else "WOULD_UPDATE",
                "live_status": result["status"], "msg": msg
            })
            print(f"          → LIVE=PASS | {'UPDATED' if not DRY_RUN else 'WOULD UPDATE'} has_robots=True")
            updated += 1
        else:
            # Both DB and live agree: really no robots or really blocked
            log_rows.append({
                "lead_id": lead["id"], "name": name, "url": url,
                "action": "CORRECT", "live_status": result["status"], "msg": msg
            })
            print(f"          → LIVE={result['status']} | DB is CORRECT — no change needed")
            skipped += 1

    except requests.exceptions.RequestException as e:
        print(f"          → NETWORK ERROR: {e}")
        log_rows.append({
            "lead_id": lead["id"], "name": name, "url": url,
            "action": "ERROR", "live_status": "ERR", "msg": str(e)[:80]
        })
        errors += 1

    # Rate limit: 0.5 sec between requests
    time.sleep(0.5)

    # Commit in batches of 50 (only when applying)
    if not DRY_RUN and i % 50 == 0:
        conn.commit()
        print(f"  [Batch commit at {i}]")

# Final commit
if not DRY_RUN:
    conn.commit()

conn.close()

# Write CSV log
with open(log_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["lead_id","name","url","action","live_status","msg"])
    writer.writeheader()
    writer.writerows(log_rows)

print()
print("=" * 70)
print(f"SUMMARY:")
print(f"  Total checked  : {len(leads)}")
print(f"  Updated to PASS: {updated} {'(dry-run — no DB changes)' if DRY_RUN else ''}")
print(f"  Already correct: {skipped}")
print(f"  Network errors : {errors}")
print(f"  Log saved to   : {log_path}")
print()
if DRY_RUN:
    print("Re-run with --apply to actually update the database.")
