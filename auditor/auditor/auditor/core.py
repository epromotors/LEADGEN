# auditor/core.py — Page fetcher and session utilities

import ssl
import socket
import urllib.parse
import warnings
import requests
import urllib3
from bs4 import BeautifulSoup
import time
from config import REQUEST_HEADERS, TIMEOUT

# Suppress SSL warnings globally — we handle SSL errors explicitly
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_BODY_BYTES = 5 * 1024 * 1024       # 5 MB reasonable limit for HTML/XML documents
MAX_READ_TIME = min(TIMEOUT, 10.0)      # 10s cumulative elapsed time budget for consuming response body


class BoundedText(str):
    """
    String subclass holding response text with explicit boundedness metadata:
    - is_truncated: True if stream exceeded max_bytes
    - is_timed_out: True if stream consumption hit max_elapsed
    - bytes_read: total byte count consumed from the network stream
    """
    is_truncated: bool
    is_timed_out: bool
    bytes_read: int

    def __new__(
        cls,
        content: str,
        is_truncated: bool = False,
        is_timed_out: bool = False,
        bytes_read: int = 0,
    ):
        obj = super().__new__(cls, content)
        obj.is_truncated = is_truncated
        obj.is_timed_out = is_timed_out
        obj.bytes_read = bytes_read
        return obj


class BoundedBytes(bytes):
    """
    Bytes subclass holding response bytes with explicit boundedness metadata:
    - is_truncated: True if stream exceeded max_bytes
    - is_timed_out: True if stream consumption hit max_elapsed
    - bytes_read: total byte count consumed from the network stream
    """
    is_truncated: bool
    is_timed_out: bool
    bytes_read: int

    def __new__(
        cls,
        content: bytes,
        is_truncated: bool = False,
        is_timed_out: bool = False,
        bytes_read: int = 0,
    ):
        obj = super().__new__(cls, content)
        obj.is_truncated = is_truncated
        obj.is_timed_out = is_timed_out
        obj.bytes_read = bytes_read
        return obj


def read_response_text(
    resp: requests.Response,
    max_bytes: int = MAX_BODY_BYTES,
    max_elapsed: float = MAX_READ_TIME,
) -> BoundedText:
    """
    Safely stream and consume response body strictly up to max_bytes or max_elapsed.
    Enforces a strict byte limit before retaining chunks (retaining only the permitted
    portion if a chunk exceeds the remaining budget).
    Returns BoundedText with .is_truncated and .is_timed_out metadata.
    """
    if not hasattr(resp, "iter_content"):
        raw_text = getattr(resp, "text", "")
        raw_encoded = raw_text.encode("utf-8", errors="replace")
        if len(raw_encoded) > max_bytes:
            sliced = raw_encoded[:max_bytes].decode("utf-8", errors="replace")
            return BoundedText(sliced, is_truncated=True, bytes_read=max_bytes)
        return BoundedText(raw_text, is_truncated=False, bytes_read=len(raw_encoded))

    is_truncated = False
    is_timed_out = False
    chunks = []
    total_bytes = 0
    start = time.perf_counter()

    try:
        iterator = resp.iter_content(chunk_size=65536)
        if hasattr(iterator, "__iter__"):
            for chunk in iterator:
                if not chunk:
                    continue
                if not isinstance(chunk, (bytes, bytearray)):
                    break

                remaining = max_bytes - total_bytes
                if remaining <= 0:
                    is_truncated = True
                    break

                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total_bytes += remaining
                    is_truncated = True
                    break

                chunks.append(chunk)
                total_bytes += len(chunk)

                if total_bytes >= max_bytes:
                    is_truncated = True
                    break

                if (time.perf_counter() - start) >= max_elapsed:
                    is_timed_out = True
                    break

        try:
            resp.is_truncated = is_truncated
            resp.is_timed_out = is_timed_out
            resp.bytes_read = total_bytes
        except Exception:
            pass

        if chunks:
            raw = b"".join(chunks)
            encoding = getattr(resp, "encoding", None) or "utf-8"
            try:
                decoded = raw.decode(encoding, errors="replace")
            except Exception:
                decoded = raw.decode("utf-8", errors="replace")
            return BoundedText(decoded, is_truncated=is_truncated, is_timed_out=is_timed_out, bytes_read=total_bytes)
    except Exception:
        pass

    if chunks:
        raw = b"".join(chunks)
        encoding = getattr(resp, "encoding", None) or "utf-8"
        try:
            decoded = raw.decode(encoding, errors="replace")
        except Exception:
            decoded = raw.decode("utf-8", errors="replace")
        return BoundedText(decoded, is_truncated=True, is_timed_out=is_timed_out, bytes_read=total_bytes)

    fallback_text = getattr(resp, "text", "")
    return BoundedText(fallback_text, is_truncated=is_truncated, is_timed_out=is_timed_out, bytes_read=total_bytes)


def read_response_bytes(
    resp: requests.Response,
    max_bytes: int = 512 * 1024,
    max_elapsed: float = 5.0,
) -> BoundedBytes:
    """
    Safely stream and consume binary response body strictly up to max_bytes or max_elapsed.
    Enforces a strict byte limit before retaining chunks (retaining only the permitted
    portion if a chunk exceeds the remaining budget).
    Returns BoundedBytes with .is_truncated and .is_timed_out metadata.
    """
    if not hasattr(resp, "iter_content"):
        raw_bytes = getattr(resp, "content", b"")
        if len(raw_bytes) > max_bytes:
            return BoundedBytes(raw_bytes[:max_bytes], is_truncated=True, bytes_read=max_bytes)
        return BoundedBytes(raw_bytes, is_truncated=False, bytes_read=len(raw_bytes))

    is_truncated = False
    is_timed_out = False
    chunks = []
    total_bytes = 0
    start = time.perf_counter()

    try:
        iterator = resp.iter_content(chunk_size=16384)
        if hasattr(iterator, "__iter__"):
            for chunk in iterator:
                if not chunk:
                    continue
                if not isinstance(chunk, (bytes, bytearray)):
                    break

                remaining = max_bytes - total_bytes
                if remaining <= 0:
                    is_truncated = True
                    break

                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total_bytes += remaining
                    is_truncated = True
                    break

                chunks.append(chunk)
                total_bytes += len(chunk)

                if total_bytes >= max_bytes:
                    is_truncated = True
                    break

                if (time.perf_counter() - start) >= max_elapsed:
                    is_timed_out = True
                    break

        try:
            resp.is_truncated = is_truncated
            resp.is_timed_out = is_timed_out
            resp.bytes_read = total_bytes
        except Exception:
            pass

        if chunks:
            return BoundedBytes(b"".join(chunks), is_truncated=is_truncated, is_timed_out=is_timed_out, bytes_read=total_bytes)
    except Exception:
        pass

    if chunks:
        return BoundedBytes(b"".join(chunks), is_truncated=True, is_timed_out=is_timed_out, bytes_read=total_bytes)

    fallback_bytes = getattr(resp, "content", b"")
    if len(fallback_bytes) > max_bytes:
        return BoundedBytes(fallback_bytes[:max_bytes], is_truncated=True, bytes_read=max_bytes)
    return BoundedBytes(fallback_bytes, is_truncated=is_truncated, is_timed_out=is_timed_out, bytes_read=len(fallback_bytes))


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def normalize_url(url: str) -> str:
    """
    Deterministic normalization:
    - Strips leading/trailing whitespace
    - Ensures scheme (defaults to https://)
    - Lowercases scheme and hostname
    - Normalizes path and trailing slashes deterministically
    - Preserves query parameters, strips fragment
    """
    if not url:
        return ""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    elif not path:
        path = ""
    query = parsed.query
    normalized = urllib.parse.urlunsplit((scheme, netloc, path, query, ""))
    return normalized.rstrip("/") if (not path or path == "/") else normalized


def get_origin(url: str) -> str:
    """Extract standard http(s)://hostname[:port] origin from any page or subpath URL."""
    norm = normalize_url(url)
    parsed = urllib.parse.urlsplit(norm)
    return f"{parsed.scheme}://{parsed.netloc}"


def get_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lstrip("www.")


def fetch_page(url: str, session: requests.Session) -> dict:
    """
    Fetch a URL and return rich response metadata.
    Returns dict with keys: ok, url, final_url, is_redirected, redirect_url, status_code,
                            html, soup, headers, error, truncated
    """
    result = {
        "ok": False, "url": url, "final_url": url,
        "is_redirected": False, "redirect_url": None,
        "status_code": None, "html": "", "soup": None,
        "headers": {}, "error": None, "truncated": False,
    }
    try:
        with session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False, stream=True) as resp:
            result["ok"] = True
            result["final_url"] = resp.url
            result["is_redirected"] = normalize_url(url) != normalize_url(resp.url)
            result["redirect_url"] = resp.url if result["is_redirected"] else None
            result["status_code"] = resp.status_code
            html_text = read_response_text(resp, max_bytes=MAX_BODY_BYTES, max_elapsed=MAX_READ_TIME)
            result["html"] = html_text
            result["headers"] = dict(resp.headers)
            result["truncated"] = getattr(html_text, "is_truncated", False)
            if result["truncated"]:
                result["headers"]["x-content-truncated"] = "true"
            result["soup"] = BeautifulSoup(html_text, "lxml")
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
        try:
            code = r.status_code
        finally:
            r.close()
        return code
    except Exception:
        try:
            with session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False, stream=True) as r:
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
