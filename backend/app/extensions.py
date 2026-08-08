"""
Vigil AI — Flask Extensions (Production Hardened)
=====================================================
Rate limiter with secure IP extraction and structured logging.

Security:
  - X-Forwarded-For is NOT trusted by default (spoofable)
  - Uses VIGIL_TRUSTED_PROXIES to configure trusted proxy IPs
  - Falls back to request.remote_addr (direct connection IP)
"""

import os
import ipaddress
from flask import request
from flask_limiter import Limiter

from app.core.logger import get_logger

_ext_logger = get_logger('vigil.extensions')


# ── Secure IP Extraction ──────────────────────────────────────────────────────
# SECURITY FIX: Never blindly trust X-Forwarded-For.
# Only extract forwarded IP when the direct connection is from a trusted proxy.

_TRUSTED_PROXIES = set()
_trusted_raw = os.getenv('VIGIL_TRUSTED_PROXIES', '').strip()
if _trusted_raw:
    for proxy in _trusted_raw.split(','):
        proxy = proxy.strip()
        if proxy:
            try:
                # Support both individual IPs and CIDR ranges
                _TRUSTED_PROXIES.add(ipaddress.ip_network(proxy, strict=False))
            except ValueError:
                _ext_logger.warning(f"Invalid trusted proxy: {proxy}")

_ext_logger.info(
    f"Trusted proxies configured: {len(_TRUSTED_PROXIES)} "
    f"({'NONE — X-Forwarded-For ignored' if not _TRUSTED_PROXIES else ', '.join(str(p) for p in _TRUSTED_PROXIES)})"
)


def _is_trusted_proxy(ip_str: str) -> bool:
    """Check if the given IP is in the trusted proxy list."""
    if not _TRUSTED_PROXIES:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in _TRUSTED_PROXIES)
    except ValueError:
        return False


def _get_real_ip() -> str:
    """
    Extract the real client IP securely.

    Rules:
      1. If request.remote_addr is a trusted proxy AND X-Forwarded-For is set,
         use the LEFTMOST (client) IP from X-Forwarded-For.
      2. Otherwise, use request.remote_addr (the direct TCP connection IP).

    This prevents rate limiter bypass via spoofed X-Forwarded-For headers
    when NOT behind a trusted reverse proxy.
    """
    remote = request.remote_addr or '127.0.0.1'

    if _is_trusted_proxy(remote):
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            # Take the leftmost IP (original client)
            client_ip = xff.split(',')[0].strip()
            if client_ip:
                return client_ip

    return remote


# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=_get_real_ip,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)


# ── Structured Logging ────────────────────────────────────────────────────────
# Delegated to app.core.logger — single source of truth.
# The `logger` export is kept for backward compatibility with app/__init__.py.
logger = get_logger('vigil')
