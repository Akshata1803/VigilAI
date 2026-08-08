"""
Vigil AI — Centralized Configuration
=====================================
Single source of truth for all tunable parameters.
Supports environment variable overrides for production deployment.
"""

import os


class Config:
    """Centralized configuration with environment variable overrides."""

    # ── Application ────────────────────────────────────────────────────────────
    APP_NAME = "Vigil AI"
    VERSION = "3.0.0"
    DEBUG = os.getenv("VIGIL_DEBUG", "false").lower() == "true"

    # ── Server ─────────────────────────────────────────────────────────────────
    HOST = os.getenv("VIGIL_HOST", "0.0.0.0")
    PORT = int(os.getenv("VIGIL_PORT", "5000"))
    THREADS = int(os.getenv("VIGIL_THREADS", "8"))

    # ── Pipeline ───────────────────────────────────────────────────────────────
    PIPELINE_MAX_WORKERS = int(os.getenv("VIGIL_PIPELINE_WORKERS", "8"))
    PIPELINE_TIMEOUT_SECONDS = int(os.getenv("VIGIL_PIPELINE_TIMEOUT", "45"))
    ANALYZER_TIMEOUT_SECONDS = int(os.getenv("VIGIL_ANALYZER_TIMEOUT", "15"))

    # ── Scanner ────────────────────────────────────────────────────────────────
    SCAN_NAV_TIMEOUT_MS = int(os.getenv("VIGIL_NAV_TIMEOUT", "15000"))
    SCAN_FALLBACK_TIMEOUT_MS = int(os.getenv("VIGIL_FALLBACK_TIMEOUT", "10000"))
    SCAN_SCROLL_MAX_PX = int(os.getenv("VIGIL_SCROLL_MAX", "15000"))
    SCAN_RENDER_WAIT_MS = int(os.getenv("VIGIL_RENDER_WAIT", "1500"))
    VIEWPORT_WIDTH = int(os.getenv("VIGIL_VIEWPORT_W", "1280"))
    VIEWPORT_HEIGHT = int(os.getenv("VIGIL_VIEWPORT_H", "800"))

    # ── ML Models ──────────────────────────────────────────────────────────────
    ML_MODEL_DIR = os.getenv(
        "VIGIL_MODEL_DIR",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "models"),
    )
    ML_CLASSIFIER_FILE = "dp_classifier.pkl"
    ML_MIN_CONFIDENCE = float(os.getenv("VIGIL_ML_MIN_CONF", "0.60"))

    # ── Decision Engine (HADE) ─────────────────────────────────────────────────
    HADE_CONF_DEFAULT = float(os.getenv("VIGIL_HADE_CONF", "0.75"))
    HADE_CONF_HIGH_IMPACT = float(os.getenv("VIGIL_HADE_CONF_HIGH", "0.65"))
    HADE_CONF_CRITICAL = float(os.getenv("VIGIL_HADE_CONF_CRIT", "0.60"))

    # ── Fusion Engine ──────────────────────────────────────────────────────────
    FUSION_WEIGHTS = {
        "dom": float(os.getenv("VIGIL_W_DOM", "0.20")),
        "text": float(os.getenv("VIGIL_W_TEXT", "0.15")),
        "visual": float(os.getenv("VIGIL_W_VISUAL", "0.10")),
        "advanced": float(os.getenv("VIGIL_W_ADV", "0.15")),
        "cookie": float(os.getenv("VIGIL_W_COOKIE", "0.15")),
        "ml": float(os.getenv("VIGIL_W_ML", "0.10")),
        "readability": float(os.getenv("VIGIL_W_READ", "0.05")),
        "link": float(os.getenv("VIGIL_W_LINK", "0.05")),
        "behavioral": float(os.getenv("VIGIL_W_BEHAV", "0.05")),
    }

    # ── Temporal Smoothing ─────────────────────────────────────────────────────
    TEMPORAL_WINDOW_SIZE = int(os.getenv("VIGIL_TEMPORAL_WINDOW", "5"))
    TEMPORAL_DECAY_FACTOR = float(os.getenv("VIGIL_TEMPORAL_DECAY", "0.85"))

    # ── Trust Score Formula ────────────────────────────────────────────────────
    TRUST_SCORE_BASE = float(os.getenv("VIGIL_TRUST_BASE", "95.0"))
    TRUST_SCORE_DECAY_K = float(os.getenv("VIGIL_TRUST_DECAY_K", "60.0"))
    TRUST_SCORE_MIN = int(os.getenv("VIGIL_TRUST_MIN", "5"))

    # ── Database ───────────────────────────────────────────────────────────────
    DB_PATH = os.getenv(
        "VIGIL_DB_PATH",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "vigil_scans.db",
        ),
    )
    DB_POOL_SIZE = int(os.getenv("VIGIL_DB_POOL", "5"))
    DB_TIMEOUT = int(os.getenv("VIGIL_DB_TIMEOUT", "10"))

    # ── Rate Limiting ──────────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT = os.getenv("VIGIL_RATE_DEFAULT", "200 per day; 50 per hour")
    RATE_LIMIT_SCAN = os.getenv("VIGIL_RATE_SCAN", "5 per minute; 50 per hour")

    # ── Screenshot Cleanup ─────────────────────────────────────────────────────
    SCREENSHOT_TTL_HOURS = int(os.getenv("VIGIL_SCREENSHOT_TTL", "24"))
    SCREENSHOT_CLEANUP_INTERVAL_S = int(os.getenv("VIGIL_CLEANUP_INTERVAL", "3600"))

    @classmethod
    def to_dict(cls):
        """Export all config values for debugging/logging."""
        return {
            k: v
            for k, v in vars(cls).items()
            if not k.startswith("_") and k.isupper()
        }
