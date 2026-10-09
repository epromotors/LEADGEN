# auditor/core.py — Page fetcher and session utilities

import ssl
import socket
import urllib.parse
import warnings
import requests
import urllib3
from bs4 import BeautifulSoup
from config import REQUEST_HEADERS, TIMEOUT

# Suppress SSL warnings globally — we handle SSL errors explicitly
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def get_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lstrip("www.")


def fetch_page(url: str, session: requests.Session) -> dict:
    """
    Fetch a URL and return rich response metadata.
    Returns dict with keys: ok, url, final_url, status_code,
                            html, soup, headers, error
    """
    result = {
        "ok": False, "url": url, "final_url": url,
        "status_code": None, "html": "", "soup": None,
        "headers": {}, "error": None,
    }
    try:
        resp = session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False)
        result["ok"] = True
        result["final_url"] = resp.url
        result["status_code"] = resp.status_code
        result["html"] = resp.text
        result["headers"] = dict(resp.headers)
        result["soup"] = BeautifulSoup(resp.text, "lxml")
    except requests.exceptions.SSLError as e:
        result["error"] = f"SSL Error: {e}"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection Error: {e}"
    except requests.exceptions.Timeout:
        result["error"] = "Request timed out"
    except Exception as e:
        result["error"] = str(e)
    return result


def check_url_status(url: str, session: requests.Session) -> int | None:
    """Lightweight HEAD check; returns status code or None on error."""
    try:
        r = session.head(url, timeout=TIMEOUT, allow_redirects=True, verify=False)
        return r.status_code
    except Exception:
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False, stream=True)
            return r.status_code
        except Exception:
            return None


def _result(status: str, message: str, fix: str = "", detail: str = "", *, value=None,
            unit: str | None = None, evidence: list | None = None, threshold: dict | None = None) -> dict:
    return {"status": status, "message": message, "fix": fix, "detail": detail,
            "value": value, "unit": unit, "evidence": evidence or [], "threshold": threshold or {}}


def result_pass(message: str, fix: str = "", detail: str = "", **structured) -> dict:
    return _result("PASS", message, fix, detail, **structured)

def result_warn(message: str, fix: str = "", detail: str = "", **structured) -> dict:
    return _result("WARN", message, fix, detail, **structured)

def result_fail(message: str, fix: str = "", detail: str = "", **structured) -> dict:
    return _result("FAIL", message, fix, detail, **structured)
