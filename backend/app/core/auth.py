"""
Vigil AI — API Key Authentication
=====================================
Lightweight API key guard for all scan endpoints.

Usage:
    Set VIGIL_API_KEY env var to enable authentication.
    If NOT set (or empty), auth is DISABLED (dev mode).

    Client sends: 'X-API-Key: <key>' header  OR
                  '?api_key=<key>' query param

Security:
    - Constant-time comparison (prevents timing attacks)
    - Logs failed attempts with IP for rate-limit correlation
    - Returns 401 with no implementation detail leakage
"""

import os
import hmac
import functools
from flask import request, jsonify

from app.core.logger import get_logger

logger = get_logger('vigil.auth')

# Read API key from environment — empty string = auth disabled
_API_KEY = os.getenv('VIGIL_API_KEY', '').strip()
AUTH_ENABLED = bool(_API_KEY)


def _constant_time_eq(a: str, b: str) -> bool:
    """Timing-safe string comparison."""
    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))


def require_api_key(f):
    """
    Decorator: enforce API key auth on a route.

    If VIGIL_API_KEY is not set, passes through (dev mode).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)

        # S-2 FIX: Only accept API key from header — query params leak into logs
        provided = request.headers.get('X-API-Key', '').strip()

        if not provided or not _constant_time_eq(provided, _API_KEY):
            # Use secure IP extraction (same logic as rate limiter)
            from app.extensions import _get_real_ip
            ip = _get_real_ip()
            logger.warning(f"Auth failure from {ip} — invalid API key")
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Valid X-API-Key header required.',
                'status': 'error',
            }), 401

        return f(*args, **kwargs)

    return decorated
