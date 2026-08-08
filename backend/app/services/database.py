"""
Vigil AI — Database Layer v2.0 (Connection Pooled SQLite)
==========================================================
UPGRADED from raw sqlite3.connect() per call to a thread-safe connection pool.

Improvements:
  - Connection pooling (configurable pool size)
  - Context-managed connections (no leaked handles)
  - WAL mode for concurrent reads during writes
  - Structured error handling with DatabaseError
  - Automatic retry on SQLITE_BUSY (transient lock contention)
"""

import sqlite3
import json
import os
import threading
import time
from queue import Queue, Empty

from app.core.config import Config
from app.core.logger import get_logger
from app.core.exceptions import DatabaseError

logger = get_logger('vigil.database')

DB_PATH = Config.DB_PATH


class ConnectionPool:
    """Thread-safe SQLite connection pool."""

    def __init__(self, db_path, pool_size=5, timeout=10):
        self._db_path = db_path
        self._pool_size = pool_size
        self._timeout = timeout
        self._pool = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._created = 0
        self._initialized = False

    def _create_connection(self):
        """Create a new connection with optimal SQLite settings."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=self._timeout)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA cache_size=-8000')  # 8MB cache
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self):
        """Lazy DB initialization — only on first actual use (FIX C-4)."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                conn = self._create_connection()
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS scans (
                        scan_id        TEXT PRIMARY KEY,
                        url            TEXT NOT NULL,
                        domain         TEXT NOT NULL,
                        trust_score    INTEGER NOT NULL,
                        grade          TEXT,
                        total_patterns INTEGER DEFAULT 0,
                        risk_label     TEXT DEFAULT '',
                        timestamp      TEXT,
                        report_json    TEXT NOT NULL
                    )
                ''')
                # Performance indexes for production query patterns
                conn.execute('CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp DESC)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_scans_domain ON scans(domain)')
                conn.commit()
                self._pool.put(conn)
                self._created = 1
                self._initialized = True
                logger.info("Database initialized (lazy)")
            except Exception as e:
                logger.error(f"Database initialization failed: {e}")

    def get(self):
        """Get a connection from the pool (or create one if pool not full). FIX H-2: better locking."""
        self._ensure_initialized()
        try:
            conn = self._pool.get_nowait()
            # Test the connection is still alive
            try:
                conn.execute('SELECT 1')
                return conn
            except sqlite3.Error:
                with self._lock:
                    self._created = max(0, self._created - 1)
        except Empty:
            pass

        with self._lock:
            if self._created < self._pool_size:
                self._created += 1
                return self._create_connection()

        # Pool is full, wait for one to be returned
        try:
            conn = self._pool.get(timeout=self._timeout)
            return conn
        except Empty:
            raise DatabaseError(f"Connection pool exhausted (size={self._pool_size})")

    def put(self, conn):
        """Return a connection to the pool."""
        try:
            self._pool.put_nowait(conn)
        except Exception:
            # Pool full, close the extra connection
            try:
                conn.close()
            except Exception:
                pass


# Global connection pool
_pool = ConnectionPool(DB_PATH, pool_size=Config.DB_POOL_SIZE, timeout=Config.DB_TIMEOUT)


class PooledConnection:
    """Context manager for pooled database connections."""

    def __init__(self):
        self.conn = None

    def __enter__(self):
        self.conn = _pool.get()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type is None:
                try:
                    self.conn.commit()
                except Exception:
                    pass
            _pool.put(self.conn)
        return False


def get_db():
    """Get a pooled database connection (backward compatible)."""
    return _pool.get()


def _retry(func, max_retries=3, delay=0.1):
    """Retry a database operation on SQLITE_BUSY."""
    for attempt in range(max_retries):
        try:
            return func()
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() or 'busy' in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
            raise
    raise DatabaseError("Database operation failed after retries")


def init_db():
    """Initialize database schema (called lazily by pool, not at import time)."""
    _pool._ensure_initialized()


# NOTE: init_db() is NO LONGER called at import time (FIX C-4)
# The pool self-initializes on first use via _ensure_initialized()


def save_scan(data):
    """Save scan report to database with retry logic."""
    def _save():
        scan_id = data.get('scan_id')
        url = data.get('url', '')
        domain = data.get('domain', '')
        trust_score = data.get('trust_score', 0)

        grade_info = data.get('grade', {})
        grade = grade_info.get('letter', '') if isinstance(grade_info, dict) else str(grade_info)

        total_patterns = data.get('total_patterns', 0)

        risk_info = data.get('risk_level', {})
        risk_label = risk_info.get('label', '') if isinstance(risk_info, dict) else str(risk_info)

        timestamp = data.get('timestamp', '')
        report_json = json.dumps(data, ensure_ascii=False)

        with PooledConnection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO scans
                (scan_id, url, domain, trust_score, grade, total_patterns, risk_label, timestamp, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (scan_id, url, domain, trust_score, grade, total_patterns, risk_label, timestamp, report_json))
            conn.commit()

    try:
        _retry(_save)
    except Exception as e:
        logger.error(f"Error saving scan: {e}")


def get_history(page=1, limit=50):
    """Get recent scan history with pagination."""
    try:
        offset = (max(1, page) - 1) * limit
        with PooledConnection() as conn:
            rows = conn.execute(
                'SELECT scan_id, url, domain, trust_score, grade, total_patterns, risk_label, timestamp '
                'FROM scans ORDER BY timestamp DESC LIMIT ? OFFSET ?', (limit, offset)
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []


def get_scan(scan_id):
    """Get a specific scan report by ID."""
    try:
        with PooledConnection() as conn:
            row = conn.execute(
                'SELECT report_json FROM scans WHERE scan_id = ?', (scan_id,)
            ).fetchone()
            if row:
                return json.loads(row['report_json'])
    except Exception as e:
        logger.error(f"Error fetching scan {scan_id}: {e}")
    return None


def get_category_counts(limit=50):
    """Get top dark pattern categories from recent scans."""
    try:
        with PooledConnection() as conn:
            rows = conn.execute(
                'SELECT report_json FROM scans ORDER BY timestamp DESC LIMIT ?', (limit,)
            ).fetchall()
            cat_counter = {}
            for row in rows:
                try:
                    report = json.loads(row['report_json'])
                    for f in report.get('findings', []):
                        cat = f.get('category', '')
                        if cat:
                            cat_counter[cat] = cat_counter.get(cat, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    continue
            return sorted(cat_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    except Exception as e:
        logger.error(f"Error fetching category counts: {e}")
        return []


def get_stats():
    """Get aggregate statistics."""
    try:
        with PooledConnection() as conn:
            row = conn.execute(
                'SELECT COUNT(*) as total_scans, '
                'AVG(trust_score) as avg_trust_score, '
                'SUM(CASE WHEN risk_label LIKE "%High%" OR risk_label LIKE "%Critical%" THEN 1 ELSE 0 END) as high_risk_count, '
                'MIN(trust_score) as min_trust_score, '
                'MAX(trust_score) as max_trust_score, '
                'AVG(total_patterns) as avg_patterns '
                'FROM scans'
            ).fetchone()
            return {
                'total_scans': row['total_scans'] or 0,
                'avg_trust_score': round(row['avg_trust_score'] or 0, 1),
                'high_risk_count': row['high_risk_count'] or 0,
                'min_trust_score': row['min_trust_score'] or 0,
                'max_trust_score': row['max_trust_score'] or 0,
                'avg_patterns': round(row['avg_patterns'] or 0, 1),
            }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")

    return {
        'total_scans': 0, 'avg_trust_score': 0, 'high_risk_count': 0,
        'min_trust_score': 0, 'max_trust_score': 0, 'avg_patterns': 0,
    }
