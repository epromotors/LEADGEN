"""
Standalone email preview generator.
Extracts build_html_email without triggering SQLAlchemy/DB imports.
"""
import sys, types, unittest.mock

# ── Stub out all app.* heavy imports so we can import outreach_engine standalone
_stubs = [
    "sqlalchemy", "sqlalchemy.ext", "sqlalchemy.ext.asyncio",
    "sqlalchemy.future", "sqlalchemy.orm",
]
# Create minimal stubs
for name in _stubs:
    sys.modules.setdefault(name, types.ModuleType(name))

# Stub app modules that outreach_engine imports
for mod in ["app", "app.database", "app.models", "app.config", "app.utils", "app.utils.spintax"]:
    sys.modules.setdefault(mod, types.ModuleType(mod))

# Stub select
sys.modules["sqlalchemy"].select = lambda *a, **kw: None

# Stub AsyncSessionLocal
sys.modules["app.database"].AsyncSessionLocal = None

# Stub models
for cls in ["Lead", "Audit", "Campaign", "CampaignEmailLog", "CampaignStatus", "ActivityLog", "AuditStatus", "LeadStatus"]:
    setattr(sys.modules["app.models"], cls, type(cls, (), {}))

# Stub settings
class _Settings:
    smtp_accounts = []
    test_mode = False
sys.modules["app.config"].settings = _Settings()

# Inject working spintax
import importlib.util, os
spec = importlib.util.spec_from_file_location("spintax", "app/utils/spintax.py")
spintax_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spintax_mod)
sys.modules["app.utils.spintax"] = spintax_mod
sys.modules["app.utils.spintax"].process_template = spintax_mod.process_template

# ── Now import the engine ─────────────────────────────────────────────────────
sys.path.insert(0, ".")
loader = importlib.util.spec_from_file_location("outreach_engine", "app/engines/outreach_engine.py")
eng = importlib.util.module_from_spec(loader)
loader.loader.exec_module(eng)

# ── Mock lead & audit objects ─────────────────────────────────────────────────
class MockAudit:
    ssl_valid          = False
    has_sitemap        = False
    has_robots         = True
    broken_links_count = 3
    missing_h1         = False
    missing_alt_count  = 5
    uses_webp          = False
    has_json_ld        = False
    mobile_friendly    = True
    missing_social     = ["instagram", "linkedin"]

class MockLead:
    business_name = "Freight International LLC"
    website       = "https://www.freightinternational.ae"

# ── Generate ──────────────────────────────────────────────────────────────────
html = eng.build_html_email(MockLead(), MockAudit())
with open("email_preview.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"email_preview.html written — {len(html):,} bytes")
print("Open: file:///C:/Users/LENOVO/LEADGEN/backend/email_preview.html")
