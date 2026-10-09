"""Fix double comma syntax error introduced by patch."""
from pathlib import Path
ENGINE = Path(__file__).resolve().parents[1] / "backend" / "app" / "engines" / "audit_engine.py"
src = ENGINE.read_bytes().decode("utf-8")
fixed = src.replace('"email_source": email_source,,', '"email_source": email_source,')
ENGINE.write_bytes(fixed.encode("utf-8"))
print("Fixed double comma:", fixed != src)
