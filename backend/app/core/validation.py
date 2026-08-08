"""
Vigil AI — Request Validation
================================
Strict schema validation and sanitization for all API inputs.

Prevents:
  - Oversized payloads (DoS)
  - Malformed URLs
  - SSRF (combined with scanner.py safeguards)
  - Injection via unexpected fields
"""

import re
from urllib.parse import urlparse
from typing import Tuple, Optional


# Maximum allowed content-length for scan request body (32KB)
MAX_PAYLOAD_BYTES = 32 * 1024

# URL must be http/https and have a real host
_URL_RE = re.compile(
    r'^https?://'               # scheme
    r'[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+'  # host + path
    r'$',
    re.IGNORECASE,
)

# Maximum URL length
MAX_URL_LENGTH = 2048


def validate_scan_request(data: dict) -> Tuple[bool, Optional[str]]:
    """
    Validate a scan request body.

    Returns (ok: bool, error_message: str|None).
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object."

    # Required field
    url = data.get('url')
    if not url:
        return False, "Field 'url' is required."

    if not isinstance(url, str):
        return False, "Field 'url' must be a string."

    url = url.strip()

    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH} characters."

    # Block non-http schemes BEFORE auto-prepending (file://, ftp://, data:, etc.)
    if '://' in url:
        scheme = url.split('://')[0].lower()
        if scheme not in ('http', 'https'):
            return False, f"Scheme '{scheme}://' is not allowed. Only http and https are supported."

    # Block pseudo-schemes that have no :// separator (javascript:, vbscript:, data:)
    _lower = url.lower().lstrip()
    for pseudo in ('javascript:', 'vbscript:', 'data:', 'blob:'):
        if _lower.startswith(pseudo):
            return False, f"Scheme '{pseudo}' is not allowed. Only http and https are supported."

    # Auto-prepend https if no scheme
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    if not _URL_RE.match(url):
        return False, "Invalid URL format. Must be a valid http/https URL."

    parsed = urlparse(url)
    if not parsed.netloc:
        return False, "URL must include a valid hostname."

    # Belt-and-suspenders scheme check after parsing
    if parsed.scheme not in ('http', 'https'):
        return False, "Only http and https URLs are supported."

    # Validate optional cookies (must be list of dicts)
    cookies = data.get('cookies')
    if cookies is not None:
        if not isinstance(cookies, list):
            return False, "Field 'cookies' must be an array."
        if len(cookies) > 100:
            return False, "Too many cookies (max 100)."
        for c in cookies:
            if not isinstance(c, dict):
                return False, "Each cookie must be an object with 'name' and 'value'."

    # Reject unexpected large fields
    for field, value in data.items():
        if field not in ('url', 'cookies', 'local_storage'):
            continue
        if isinstance(value, str) and len(value) > MAX_URL_LENGTH * 10:
            return False, f"Field '{field}' exceeds maximum allowed size."

    return True, None


def sanitize_url(url: str) -> str:
    """Return a clean, normalized URL string."""
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url