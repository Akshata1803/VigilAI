"""
Vigil AI — Structured Logging System
======================================
Production-grade structured logging with:
  - JSON-formatted log output for log aggregators
  - Correlation IDs for request tracing
  - Automatic context injection (scan_id, url, analyzer)
  - Rotating file handler with size limits
  - Console output for development
"""

import logging
import json
import time
import uuid
import threading
from logging.handlers import RotatingFileHandler


_thread_local = threading.local()


def set_correlation_id(correlation_id=None):
    """Set a correlation ID for the current request/thread."""
    _thread_local.correlation_id = correlation_id or str(uuid.uuid4())[:8]
    return _thread_local.correlation_id


def get_correlation_id():
    """Get the current thread's correlation ID."""
    return getattr(_thread_local, 'correlation_id', 'no-ctx')


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for production log aggregation."""

    def format(self, record):
        log_entry = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'correlation_id': get_correlation_id(),
            'message': record.getMessage(),
        }

        # Inject extra context fields
        for field in ('scan_id', 'url', 'analyzer', 'duration_ms', 'findings_count'):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        if record.exc_info and record.exc_info[1]:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Human-readable formatter for console/dev mode."""

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, '')
        cid = get_correlation_id()
        prefix = f"{color}{record.levelname:8s}{self.RESET}"
        timestamp = self.formatTime(record, '%H:%M:%S')
        msg = record.getMessage()
        return f"[{timestamp}] {prefix} [{cid}] {msg}"


def get_logger(name='vigil'):
    """
    Get or create a structured logger.

    Usage:
        logger = get_logger('vigil.pipeline')
        logger.info('Pipeline started', extra={'scan_id': '1234', 'url': 'https://...'})
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if __debug__ else logging.INFO)
    logger.propagate = False

    # File handler — structured JSON for production (FIX L-6: configurable path)
    try:
        import os
        log_path = os.getenv('VIGIL_LOG_PATH', 'vigil_enterprise.log')
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,   # 10 MB
            backupCount=5,
            encoding='utf-8',
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(StructuredFormatter())
        logger.addHandler(file_handler)
    except (OSError, PermissionError):
        pass  # Graceful: skip file handler if path is not writable

    # Console handler — human-readable for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(HumanFormatter())
    logger.addHandler(console_handler)

    return logger
