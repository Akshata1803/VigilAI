"""
Vigil AI — Scan Result Cache
==============================
TTL-based in-process cache for scan results.
Prevents re-scanning the same domain within a configurable window.

Thread-safe. Evicts stale entries automatically via TTLCache.
"""

import hashlib
import threading
import time
import os
from typing import Optional, Dict, Any

from cachetools import TTLCache


# TTL in seconds — configurable via env var (default 5 minutes)
_CACHE_TTL = int(os.getenv('VIGIL_CACHE_TTL', '300'))
_CACHE_MAX = int(os.getenv('VIGIL_CACHE_MAX', '200'))

_cache: TTLCache = TTLCache(maxsize=_CACHE_MAX, ttl=_CACHE_TTL)
_lock = threading.Lock()

# FIX D-3: Track actual hit/miss counts instead of nonsensical formula
_hits = 0
_misses = 0


def _make_key(url: str) -> str:
    """Normalize URL and hash it into a compact key."""
    normalized = url.lower().strip().rstrip('/')
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def get_cached(url: str) -> Optional[Dict[str, Any]]:
    """Return a cached scan result for this URL, or None if not cached / expired."""
    global _hits, _misses
    key = _make_key(url)
    with _lock:
        result = _cache.get(key)
        if result is not None:
            _hits += 1
        else:
            _misses += 1
        return result


def set_cached(url: str, result: Dict[str, Any]) -> None:
    """Cache a scan result for this URL."""
    key = _make_key(url)
    with _lock:
        _cache[key] = result


def invalidate(url: str) -> None:
    """Explicitly remove cached result for a URL."""
    key = _make_key(url)
    with _lock:
        _cache.pop(key, None)


def cache_stats() -> Dict[str, Any]:
    """Return current cache statistics."""
    with _lock:
        total = _hits + _misses
        return {
            'size': len(_cache),
            'maxsize': _cache.maxsize,
            'ttl_seconds': _cache.ttl,
            'hits': _hits,
            'misses': _misses,
            'hit_rate': round(_hits / total, 3) if total > 0 else 0.0,
        }

