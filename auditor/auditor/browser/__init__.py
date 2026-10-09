"""Browser sub-package for the LEADGEN auditor.

Exports the public interface used by audit_engine.py:
    - BrowserEvidence   (typed evidence dataclass)
    - BrowserProvider   (capture implementation)
    - BrowserConfig     (configuration dataclass)
    - BrowserStatus     (status enum strings)
    - is_browser_enabled (configuration helper)

Do NOT import from this package at module-load time if you only need it
conditionally.  Use lazy imports:

    from browser.provider import BrowserProvider, BrowserConfig, BrowserEvidence
"""
from browser.provider import (
    BrowserEvidence,
    BrowserProvider,
    BrowserConfig,
    BrowserStatus,
    is_browser_enabled,
)

__all__ = [
    "BrowserEvidence",
    "BrowserProvider",
    "BrowserConfig",
    "BrowserStatus",
    "is_browser_enabled",
]
