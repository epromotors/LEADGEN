"""Patch only the return dict of _run_audit_sync to add browser evidence."""
from pathlib import Path
import re

ENGINE = Path(__file__).resolve().parents[1] / "backend" / "app" / "engines" / "audit_engine.py"
src = ENGINE.read_bytes().decode("utf-8")

BROWSER_CAPTURE = '''
    # ── Phase 2: browser evidence capture ─────────────────────────────────────
    # Runs only when BROWSER_ENABLED=true.  A browser failure NEVER aborts the
    # HTTP audit or changes any factor status or score.
    browser_evidence: dict = {}
    browser_status: str = "DISABLED"
    try:
        if _BROWSER_MODULE_AVAILABLE:
            _bcfg = BrowserConfig.from_env()
            if _bcfg.enabled:
                _provider = BrowserProvider(_bcfg)
                _bev = _provider.capture(url)
                browser_evidence = _bev.to_dict()
                browser_status   = _bev.provider_status
                logger.info(
                    "[audit_engine] Browser evidence status=%s elapsed=%d ms for %s",
                    browser_status, _bev.elapsed_ms, url,
                )
                _annotate_browser_comparisons(audit_results, _bev)
            else:
                browser_status = "DISABLED"
        else:
            browser_status = "UNAVAILABLE"
    except Exception as _bexc:
        browser_status   = "ERROR"
        browser_evidence = {"provider_status": "ERROR", "provider_error": str(_bexc)}
        logger.exception("[audit_engine] Browser evidence capture failed for %s", url)

'''

# Use regex to find the return dict of _run_audit_sync
# Look for the return that starts with audit_results and ends with email_source
pattern = re.compile(
    r'(    return \{[^}]*?"email_source": email_source,\s*\})',
    re.DOTALL
)

def replacer(m):
    old = m.group(0)
    if "browser_evidence" in old:
        return old  # already patched
    # Add browser capture block before return, and add fields to return dict
    new_return = old.rstrip('}').rstrip() + ',\n        "browser_evidence": browser_evidence,\n        "browser_status":   browser_status,\n    }'
    return BROWSER_CAPTURE + new_return

new_src = pattern.sub(replacer, src, count=1)

if new_src == src:
    print("ERROR: pattern did not match — return dict not patched")
else:
    ENGINE.write_bytes(new_src.encode("utf-8"))
    print("PATCH 2: return dict updated successfully")
