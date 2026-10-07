# LeadGen OS v4.0 — Installation Instructions
# ═══════════════════════════════════════════

## What's in this package

```
auditor/                          → DROP this entire folder into C:\Users\LENOVO\LEADGEN\
  config.py
  main.py
  auditor/
    __init__.py
    core.py
    technical.py
    onpage.py
    images.py
    links.py
    social.py
    trust.py
    crawler.py
  reporter/
    __init__.py
    pdf_report.py

backend_patch/
  audit_engine.py                 → COPY to C:\Users\LENOVO\LEADGEN\backend\app\engines\
```

---

## Step-by-Step Installation

### Step 1 — Place the auditor package
Copy the entire `auditor/` folder from this ZIP to:
```
C:\Users\LENOVO\LEADGEN\auditor\
```
Result should be:
```
C:\Users\LENOVO\LEADGEN\auditor\config.py
C:\Users\LENOVO\LEADGEN\auditor\auditor\core.py
C:\Users\LENOVO\LEADGEN\auditor\reporter\pdf_report.py
... etc
```

### Step 2 — Backup the old backend files
```powershell
cd C:\Users\LENOVO\LEADGEN\backend\app\engines\
copy audit_engine.py audit_engine_v3_backup.py
copy pdf_engine.py   pdf_engine_old.py
```

### Step 3 — Install the new audit engine
Copy `backend_patch/audit_engine.py` to:
```
C:\Users\LENOVO\LEADGEN\backend\app\engines\audit_engine.py
```
(Overwrite the existing file)

### Step 4 — Install new Python dependency
```powershell
cd C:\Users\LENOVO\LEADGEN\backend
venv\Scripts\activate
pip install reportlab
```
Note: requests, beautifulsoup4, lxml are already installed — skip those.

### Step 5 — Restart the backend
```powershell
# Stop everything first
STOP.bat

# Then start again
START.bat
```

### Step 6 — Test
1. Log in to http://localhost:5174
2. Go to Leads → pick one lead with a working website
3. Click Audit (single lead)
4. Wait 60–90 seconds (new audit is more thorough)
5. Go to SEO Audits page — the row should appear
6. Click PDF — the new multi-page report should download

---

## Rollback (if anything breaks)
```powershell
cd C:\Users\LENOVO\LEADGEN\backend\app\engines\
copy audit_engine_v3_backup.py audit_engine.py
START.bat
```
System is back to v3.6 instantly.
